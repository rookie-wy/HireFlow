import uuid
import json
from datetime import datetime
from app.infrastructure.llm_client import LLMClient
from app.infrastructure.mcp.email_client import EmailToolClient
from app.infrastructure.mcp.calendar_client import CalendarToolClient
from app.infrastructure.redis_client import get_redis
from app.infrastructure.guardrails import scan_output
from app.services.memory.interaction_logger import InteractionLogger
from app.core.constants import LOCK_TIMEOUT_SECONDS, IDEMPOTENT_KEY_PREFIX
from app.core.exceptions import BusinessException
import logging

logger = logging.getLogger(__name__)

class InterviewScheduler:
    def __init__(self, tenant_id: str, mcp_email_url: str = "", mcp_calendar_url: str = ""):
        self.tenant_id = tenant_id
        # 在实际项目中，URL 应从配置注入，此处简化
        self.email_client = EmailToolClient(mcp_email_url or "http://localhost:9000")
        self.calendar_client = CalendarToolClient(mcp_calendar_url or "http://localhost:9001")
        self.redis = get_redis()

    async def generate_draft(self, job_title: str, candidate_name: str, candidate_email: str,
                             proposed_times: list) -> dict:
        """生成面试邀请草稿"""
        llm = LLMClient()
        prompt = f"""为候选人{candidate_name}({candidate_email})生成面试邀请邮件草稿。
        岗位：{job_title}
        提议时间选项：{', '.join(proposed_times)}
        邮件应包含：问候语、面试岗位、时间选项、回复方式。输出JSON，包含 subject 和 body。"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        draft = json.loads(resp.choices[0].message.content)
        # 安全处理（输出脱敏）
        draft['body'] = scan_output(draft['body'])
        return {
            "candidate_email": candidate_email,
            "subject": draft['subject'],
            "body": draft['body'],
            "proposed_times": proposed_times
        }

    async def confirm_and_send(self, draft: dict, job_id: str, candidate_id: str,
                               user_id: str, selected_time: str = None) -> dict:
        """确认并发送面试邀请，同时创建日历事件"""
        # 幂等键
        idempotent_key = f"idem:interview:{candidate_id}:{job_id}"
        lock_acquired = self.redis.set(idempotent_key, str(uuid.uuid4()), nx=True, ex=86400)  # 24h
        if not lock_acquired:
            raise BusinessException(message="Interview invitation already sent, duplicate request denied")

        # 发送邮件
        try:
            email_res = await self.email_client.send_email(
                to=draft['candidate_email'],
                subject=draft['subject'],
                body=draft['body']
            )
            if email_res.get("error"):
                # 发送失败，释放锁
                self.redis.delete(idempotent_key)
                raise BusinessException(f"Email send failed: {email_res['error']}")
            email_id = email_res.get("email_id", str(uuid.uuid4()))
        except Exception as e:
            self.redis.delete(idempotent_key)
            raise e

        # 创建日历事件（使用选中时间或第一个提议时间）
        event_time = selected_time or draft['proposed_times'][0]
        try:
            cal_res = await self.calendar_client.create_event(
                title=f"面试: {draft.get('job_title', '招聘面试')}",
                attendees=[draft['candidate_email']],
                start_time=event_time,
                end_time=event_time,  # 实际应用中应从提议时间解析结束时间，此处简化
                description=draft['body']
            )
        except Exception:
            logger.error("Calendar event creation failed, but email was sent")

        # 记录日志
        InteractionLogger.log_event(
            tenant_id=self.tenant_id,
            session_id="",  # 由调用方提供
            user_id=user_id,
            event_type="interview_send",
            target_id=candidate_id,
            feedback=None
        )

        return {
            "status": "sent",
            "email_id": email_id,
            "calendar_event_id": cal_res.get("event_id", "")
        }

    async def handle_reply(self, candidate_email: str, reply_body: str, current_job_id: str, candidate_id: str):
        """处理候选人邮件回复，支持多轮协商"""
        llm = LLMClient()
        prompt = f"""分析候选人回复邮件，判断其意图，提取建议时间（如果有）。
        回复内容：{reply_body}
        输出JSON：{{"intent": "accept" | "propose_new_time" | "decline", "new_times": [], "message": "..."}}"""
        messages = [{"role": "user", "content": prompt}]
        resp = llm.completion(messages)
        analysis = json.loads(resp.choices[0].message.content)

        if analysis["intent"] == "accept":
            # 自动确认原时间，发送确认邮件
            # ... 调用 confirm_and_send 或仅发送确认信
            return {"status": "confirmed", "action": "send_confirmation"}
        elif analysis["intent"] == "propose_new_time":
            # 生成新的草稿，要求HR确认
            new_draft = await self.generate_draft(
                job_title="",  # 从上下文获取
                candidate_name="",
                candidate_email=candidate_email,
                proposed_times=analysis.get("new_times", [])
            )
            return {"status": "negotiation", "new_draft": new_draft}
        else:
            return {"status": "declined"}