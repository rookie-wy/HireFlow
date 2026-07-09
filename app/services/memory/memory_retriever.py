from app.db.session import get_db
from app.db.repositories.interaction_repository import InteractionRepository
import logging

logger = logging.getLogger(__name__)

def get_high_potential_candidates(tenant_id: str, current_job_id: str, limit=5) -> list:
    """
    查询历史中进入终面或收到正面反馈但未录用的候选人ID
    """
    with get_db() as conn:
        repo = InteractionRepository(conn)
        # 查询条件：feedback='suitable' 或 event_type='final_round' 等
        # 排除当前岗位已淘汰的候选人（如有标记）
        # 返回候选ID列表
        return repo.get_high_potential_ids(tenant_id, current_job_id, limit)