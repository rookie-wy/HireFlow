"""面试调度 AI 能力：邀请草稿生成、回复意图分析、MCP 发送编排。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core.errors import BadRequestError, LLMError, UpstreamError, get_logger
from app.infra.llm_client import LLMResponse, get_llm_client
from app.infra.mcp_client import calendar_client, email_client
from app.infra.pii import mask_pii

log = get_logger(__name__)

DRAFT_PROMPT = """你是招聘协调专员。为候选人写一封面试邀请邮件。

岗位：{job_title}
候选人姓名：{candidate_name}
可选面试时间段：{proposed_times}

要求：包含亲切问候、岗位名称、时间选项（请候选人回复确认其中一个）、回复方式。150字以内。
只返回 JSON：{{"subject": "邮件主题", "body": "邮件正文"}}"""

REPLY_PROMPT = """你是招聘协调助理。分析候选人对面试邀请邮件的回复意图。

候选人回复原文：
{reply_body}

判断意图：
- accept：同意某个时间段
- propose_new_time：提出新的时间（提取到 new_times）
- decline：婉拒
- other：无法判断

只返回 JSON：{{"intent": "accept|propose_new_time|decline|other", "new_times": ["若提出新时间"], "message": "50字内备注"}}"""


class InterviewDraft(BaseModel):
    subject: str = ""
    body: str = ""
    proposed_times: list[str] = Field(default_factory=list)
    candidate_email: str = ""


class SendResult(BaseModel):
    status: str = "sent"
    email_id: str = ""
    calendar_event_id: str = ""


async def generate_draft(
    job_title: str, candidate_name: str, candidate_email: str, proposed_times: list[str],
) -> tuple[InterviewDraft, Optional[LLMResponse]]:
    if not proposed_times:
        raise BadRequestError("proposed_times 不能为空")
    client = get_llm_client()
    messages = [{"role": "user", "content": DRAFT_PROMPT.format(
        job_title=job_title, candidate_name=candidate_name or "候选人",
        proposed_times="；".join(proposed_times),
    )}]
    try:
        data, usage = client.chat_json(messages, temperature=0.4, max_tokens=500)
    except LLMError:
        raise
    draft = InterviewDraft(
        subject=str(data.get("subject") or f"面试邀请：{job_title}"),
        body=mask_pii(str(data.get("body") or "")),
        proposed_times=proposed_times,
        candidate_email=candidate_email,
    )
    return draft, usage


async def analyze_reply(reply_body: str) -> tuple[dict, Optional[LLMResponse]]:
    if not reply_body or not reply_body.strip():
        raise BadRequestError("reply_body 不能为空")
    client = get_llm_client()
    messages = [{"role": "user", "content": REPLY_PROMPT.format(reply_body=mask_pii(reply_body[:2000]))}]
    try:
        data, usage = client.chat_json(messages, temperature=0.1, max_tokens=300)
    except LLMError:
        raise
    intent = str(data.get("intent") or "other")
    if intent not in ("accept", "propose_new_time", "decline", "other"):
        intent = "other"
    result = {
        "intent": intent,
        "new_times": [str(t) for t in (data.get("new_times") or []) if str(t).strip()][:5],
        "message": mask_pii(str(data.get("message") or ""))[:200],
    }
    return result, usage


async def send_interview(
    draft: InterviewDraft, job_title: str, selected_time: Optional[str] = None,
) -> SendResult:
    """通过 MCP 工具发送邮件 + 创建日历事件。邮件失败抛错（可重试），日历失败仅告警。"""
    email = email_client()
    calendar = calendar_client()

    email_result = await email.call_tool("send_email", {
        "to": draft.candidate_email, "subject": draft.subject, "body": draft.body,
    })
    if not isinstance(email_result, dict) or email_result.get("error"):
        raise UpstreamError(f"邮件发送失败: {email_result.get('error', 'unknown')}")
    email_id = str((email_result.get("result") or {}).get("email_id") or "")

    event_id = ""
    start = selected_time or (draft.proposed_times[0] if draft.proposed_times else "")
    if start:
        cal_result = await calendar.call_tool("calendar_api", {
            "action": "create",
            "title": f"面试：{job_title}",
            "attendees": [draft.candidate_email],
            "start_time": start,
        })
        if isinstance(cal_result, dict) and not cal_result.get("error"):
            event_id = str((cal_result.get("result") or {}).get("event_id") or "")
        else:
            log.warning("calendar create failed: %s", cal_result)

    return SendResult(status="sent", email_id=email_id, calendar_event_id=event_id)
