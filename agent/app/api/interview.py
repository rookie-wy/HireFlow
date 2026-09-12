"""面试调度 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_internal_key
from app.services.interview import scheduler

router = APIRouter(dependencies=[Depends(require_internal_key)])


@router.post("/interview/draft")
async def interview_draft(payload: dict):
    """生成面试邀请邮件草稿（LLM）。"""
    draft, usage = await scheduler.generate_draft(
        job_title=str(payload.get("job_title") or ""),
        candidate_name=str(payload.get("candidate_name") or ""),
        candidate_email=str(payload.get("candidate_email") or ""),
        proposed_times=[str(t) for t in (payload.get("proposed_times") or [])],
    )
    return {
        "draft": draft.model_dump(),
        "usage": _usage(usage),
    }


@router.post("/interview/reply-intent")
async def interview_reply_intent(payload: dict):
    """候选人回复意图分析。"""
    intent, usage = await scheduler.analyze_reply(str(payload.get("reply_body") or ""))
    return {"intent": intent, "usage": _usage(usage)}


@router.post("/interview/send")
async def interview_send(payload: dict):
    """MCP 发送邮件 + 日历（backend 已做幂等）。"""
    from app.services.interview.scheduler import InterviewDraft

    draft = InterviewDraft(
        subject=str(payload.get("subject") or ""),
        body=str(payload.get("body") or ""),
        proposed_times=[str(t) for t in (payload.get("proposed_times") or [])],
        candidate_email=str(payload.get("candidate_email") or ""),
    )
    if not draft.candidate_email:
        from app.core.errors import BadRequestError

        raise BadRequestError("candidate_email 必填")
    result = await scheduler.send_interview(
        draft, job_title=str(payload.get("job_title") or ""),
        selected_time=payload.get("selected_time"),
    )
    return result.model_dump()


def _usage(u) -> dict | None:
    if u is None:
        return None
    return {
        "model_name": u.model, "tokens_prompt": u.tokens_prompt,
        "tokens_completion": u.tokens_completion, "cost": round(u.cost, 6),
    }
