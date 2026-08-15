import logging
from app.infrastructure.tasks._compat import shared_task_compat
from app.services.memory.interaction_logger import InteractionLogger

logger = logging.getLogger(__name__)


@shared_task_compat
def persist_session_snapshot(session_id: str, state: dict):
    # 将当前状态以event_type='session_snapshot'写入interaction_log
    try:
        InteractionLogger.log_event(
            tenant_id=state.get("tenant_id", ""),
            session_id=session_id,
            user_id=state.get("user_id", ""),
            event_type="session_snapshot",
            summary_text=str(state)
        )
    except Exception as e:
        # 重试或记录
        pass


@shared_task_compat
def anonymize_old_logs():
    from app.db.session import get_db
    from datetime import timedelta, datetime
    # 保留期180天
    cutoff = datetime.utcnow() - timedelta(days=180)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM interaction_log WHERE created_at < %s", (cutoff,))
        conn.commit()
