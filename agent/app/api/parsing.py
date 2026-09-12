"""解析与向量化 API。全部路由要求 X-Internal-Key。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import get_settings
from app.core.security import require_internal_key
from app.services.parsing.jd_parser import parse_jd
from app.services.parsing.resume_parser import ingest_resume, vectorize_resume_async
from app.services.parsing.skill_graph import STANDARD_SKILL_TAGS, match_skills
from app.services.parsing.vectorization import chunk_text

router = APIRouter(dependencies=[Depends(require_internal_key)])

_MAX_UPLOAD = 20 * 1024 * 1024


@router.post("/parse/jd")
async def parse_jd_endpoint(payload: dict):
    """JD 文本 → 结构化 JobDescription。"""
    parsed = parse_jd(str(payload.get("jd_text") or ""), str(payload.get("language") or "zh"))
    return {
        "title": parsed.title,
        "hard_requirements": parsed.hard_requirements,
        "soft_requirements": parsed.soft_requirements,
        "skill_graph": parsed.skill_graph,
        "job_category": parsed.job_category,
    }


@router.post("/parse/resume")
async def parse_resume_endpoint(
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
    candidate_id: str = Form(...),
):
    """简历文件 → CandidateProfile（结构化 + 技能标准化 + 向量化）。

    性能设计：
      - 解析是同步阻塞逻辑（pymupdf + LLM + CPU 嵌入），丢线程池执行，
        否则会卡住事件循环，导致并发上传排队、健康检查等接口一起被拖慢；
      - 默认向量化走**后台任务**（VECTORIZE_IN_BACKGROUND=true）：上传响应只等
        「文本提取 + LLM 抽取」，不再等约 2s 的 CPU 嵌入；粗筛有 BM25 兜底，
        向量稍后补齐不影响出结果。
    """
    content = await file.read()
    if len(content) > _MAX_UPLOAD:
        from app.core.errors import BadRequestError

        raise BadRequestError("文件超过 20MB 限制")

    in_background = get_settings().vectorize_in_background
    profile, chunks, usage = await asyncio.to_thread(
        ingest_resume,
        content,
        file.filename or "resume.pdf",
        tenant_id,
        candidate_id,
        vectorize=not in_background,
    )

    if in_background and profile.raw_text:
        # 后台补齐向量：不阻塞响应，失败只记日志（BM25 兜底）
        asyncio.create_task(
            asyncio.to_thread(vectorize_resume_async, candidate_id, tenant_id, profile.raw_text)
        )

    payload = profile.model_dump()
    # 原文不回传：简历全文长达数 KB，backend 只取结构化字段，回传纯属浪费带宽与序列化时间
    payload.pop("raw_text", None)
    return {
        **payload,
        "vector_chunks": chunks,
        "vector_pending": in_background,
        "usage": {
            "model_name": usage.model,
            "tokens_prompt": usage.tokens_prompt,
            "tokens_completion": usage.tokens_completion,
            "cost": usage.cost,
        },
    }


@router.post("/skills/normalize")
async def normalize_skills(payload: dict):
    skills = payload.get("skills") or []
    return {"skills": match_skills([str(s) for s in skills]), "standard_tags": STANDARD_SKILL_TAGS}


@router.post("/vectors/delete")
async def delete_vectors(payload: dict):
    from app.infra import chroma_client

    tenant_id = str(payload.get("tenant_id") or "")
    candidate_id = str(payload.get("candidate_id") or "")
    if not tenant_id or not candidate_id:
        from app.core.errors import BadRequestError

        raise BadRequestError("tenant_id / candidate_id 必填")
    chroma_client.delete_candidate_vectors(tenant_id, candidate_id)
    return {"deleted": True}


@router.post("/vectors/chunks")
async def preview_chunks(payload: dict):
    """调试辅助：查看分块结果。"""
    return {"chunks": chunk_text(str(payload.get("text") or ""))}
