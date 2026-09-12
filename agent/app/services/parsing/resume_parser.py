"""简历解析流水线：文本提取 → PII 脱敏 → LLM 结构化 → 技能标准化 → 向量化。

性能设计（v5.1）：
  - LLM 抽取与向量化**并行**执行（向量化只依赖原文，不依赖 LLM 结果），
    两者分别受网络与 CPU 约束，并行后阶段耗时从「相加」变为「取较大者」；
  - 全流程逐阶段埋点（metrics: parse_stage_seconds{stage=...}），便于定位慢在哪一步；
  - 调用方（API 层）用 asyncio.to_thread 执行本函数，避免阻塞事件循环导致并发上传排队。
"""
from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from app.core.errors import LLMError, ParseError, get_logger
from app.core.metrics import inc, observe, timer
from app.infra.llm_client import LLMResponse, get_llm_client
from app.infra.pii import mask_id_card
from app.services.parsing.schemas import CandidateProfile
from app.services.parsing.skill_graph import match_skills
from app.services.parsing.text_extract import extract_text
from app.services.parsing.vectorization import vectorize_candidate

log = get_logger(__name__)

# LLM 抽取送入的文本上限：简历关键信息（教育/经历/技能）常在尾部，
# 仅截断头部会丢信息，故采用「头 2200 + 尾 1200」的保留策略。
_LLM_HEAD_CHARS = 2200
_LLM_TAIL_CHARS = 1200
_LLM_MAX_TOKENS = 2000

RESUME_PROMPT = """你是一名专业的简历信息抽取引擎。从以下简历文本中抽取结构化信息，只返回 JSON：
{{
  "name": "姓名",
  "email": "邮箱",
  "phone": "手机号",
  "work_experience": [{{"company": "公司", "title": "职位", "start_date": "YYYY-MM", "end_date": "YYYY-MM 或 至今", "description": "工作内容概述"}}],
  "education": [{{"school": "学校", "degree": "学历(专科/本科/硕士/博士)", "major": "专业", "start_date": "YYYY-MM", "end_date": "YYYY-MM"}}],
  "skills": ["技能列表"]
}}

简历文本：
{resume_text}"""


def _clip_for_llm(raw_text: str) -> str:
    """头尾保留式截断：兼顾头部基本信息与尾部经历/技能。"""
    text = raw_text or ""
    if len(text) <= _LLM_HEAD_CHARS + _LLM_TAIL_CHARS:
        return text
    return text[:_LLM_HEAD_CHARS] + "\n...（中间省略）...\n" + text[-_LLM_TAIL_CHARS:]


def extract_candidate_profile(raw_text: str, *, retries: int = 2) -> tuple[CandidateProfile, LLMResponse]:
    """LLM 结构化抽取（带重试）。"""
    client = get_llm_client()
    cleaned = mask_id_card(_clip_for_llm(raw_text))
    messages = [
        {"role": "system", "content": "你是一个精确的信息抽取引擎，只输出 JSON。"},
        {"role": "user", "content": RESUME_PROMPT.format(resume_text=cleaned)},
    ]
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            data, usage = client.chat_json(messages, temperature=0.0, max_tokens=_LLM_MAX_TOKENS)
            profile = CandidateProfile(
                name=str(data.get("name") or ""),
                email=str(data.get("email") or ""),
                phone=str(data.get("phone") or ""),
                skills=[str(s).strip() for s in data.get("skills") or [] if str(s).strip()],
                raw_text=raw_text,
            )
            for w in data.get("work_experience") or []:
                if isinstance(w, dict):
                    from app.services.parsing.schemas import WorkExperience

                    profile.work_experience.append(WorkExperience(**{k: str(w.get(k) or "") for k in
                        ("company", "title", "start_date", "end_date", "description")}))
            for e in data.get("education") or []:
                if isinstance(e, dict):
                    from app.services.parsing.schemas import Education

                    profile.education.append(Education(**{k: str(e.get(k) or "") for k in
                        ("school", "degree", "major", "start_date", "end_date")}))
            return profile, usage
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning("resume extract attempt %d failed: %s", attempt + 1, exc)
    raise LLMError(cause=last_err)


def ingest_resume(
    file_bytes: bytes,
    filename: str,
    tenant_id: str,
    candidate_id: str,
    *,
    vectorize: bool = True,
) -> tuple[CandidateProfile, int, LLMResponse]:
    """简历入库流水线，返回 (profile, 向量块数, LLM用量)。

    vectorize=True：同步完成向量化（默认，兼容旧行为）；
    vectorize=False：跳过向量化，由调用方用 vectorize_resume_async 后台补齐
    （上传接口因此少等约 2s 的 CPU 嵌入；粗筛有 BM25 兜底，不会因此无结果）。
    """
    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    total_start = time.perf_counter()
    try:
        with timer("parse_stage_seconds", stage="extract"):
            raw_text = extract_text(tmp_path, suffix)
        if not raw_text:
            raise ParseError("无法从文件中提取文本（扫描件请上传 PDF 或安装 OCR）")

        # LLM 抽取（网络密集）与向量化（CPU 密集）并行：两者互不依赖，
        # 并行后耗时≈max(两者) 而不是相加（实测 LLM ~2-3s 被向量化完全掩盖）。
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-extract") as pool:
            llm_future = pool.submit(extract_candidate_profile, raw_text)
            chunks = 0
            if vectorize:
                try:
                    with timer("parse_stage_seconds", stage="vectorize"):
                        chunks = vectorize_candidate(candidate_id, tenant_id, raw_text)
                except Exception as exc:  # noqa: BLE001 向量化失败不阻塞建档
                    log.warning("vectorization failed for %s: %s", candidate_id, exc)
                    chunks = 0
            with timer("parse_stage_seconds", stage="llm"):
                profile, usage = llm_future.result()

        with timer("parse_stage_seconds", stage="skills"):
            profile.raw_text = raw_text
            # 技能标准化：规则别名优先，未命中的才走语义（标签向量已进程内缓存，不再重复嵌入）
            profile.skills = match_skills(profile.skills)

        log.info(
            "resume parsed candidate=%s chars=%d chunks=%d vectorized=%s elapsed=%.2fs",
            candidate_id, len(raw_text), chunks, vectorize, time.perf_counter() - total_start,
        )
        return profile, chunks, usage
    finally:
        observe("parse_stage_seconds", time.perf_counter() - total_start, stage="total")
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def process_resume_upload(
    file_bytes: bytes,
    filename: str,
    tenant_id: str,
    candidate_id: str,
) -> tuple[CandidateProfile, int, LLMResponse]:
    """同步版入口（保留给测试与需要「上传即可检索」的场景）。"""
    return ingest_resume(file_bytes, filename, tenant_id, candidate_id, vectorize=True)


def vectorize_resume_async(candidate_id: str, tenant_id: str, raw_text: str) -> None:
    """后台向量化（不阻塞上传响应）。失败只记日志——粗筛有 BM25 兜底，不影响可用性。"""
    start = time.perf_counter()
    try:
        with timer("parse_stage_seconds", stage="vectorize_bg"):
            chunks = vectorize_candidate(candidate_id, tenant_id, raw_text)
        inc("vectorize_bg_total", status="ok")
        log.info("background vectorize done candidate=%s chunks=%d elapsed=%.2fs",
                 candidate_id, chunks, time.perf_counter() - start)
    except Exception as exc:  # noqa: BLE001
        inc("vectorize_bg_total", status="failed")
        log.warning("background vectorize failed candidate=%s: %s", candidate_id, exc)
