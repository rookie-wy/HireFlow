from app.infrastructure.llm_client import LLMClient
from app.services.memory.interaction_logger import InteractionLogger
from app.db.repositories.interaction_repository import InteractionRepository
from app.db.session import get_db

async def generate_job_summary(tenant_id: str, job_id: str):
    # 获取该岗位所有交互日志摘要
    with get_db() as conn:
        repo = InteractionRepository(conn)
        logs = repo.get_by_job_id(job_id)  # 假设有方法
    if not logs:
        return
    # 拼接日志摘要
    log_text = "\n".join([f"{log.event_type}: {log.feedback or ''}" for log in logs])
    llm = LLMClient()
    prompt = f"为该岗位招聘过程生成复盘摘要，提取关键结论：{log_text}"
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    summary = resp.choices[0].message.content
    # 记录摘要并向量化
    InteractionLogger.log_event(
        tenant_id=tenant_id,
        session_id=None,
        user_id=None,
        event_type="job_close",
        target_id=job_id,
        summary_text=summary
    )