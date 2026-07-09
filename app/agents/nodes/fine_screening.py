from app.services.screening.fine_screening import FineScreeningEngine
from app.agents.state import AgentState
import logging

logger = logging.getLogger(__name__)

async def fine_screening_node(state: AgentState) -> AgentState:
    tenant_id = state["tenant_id"]
    job_id = state["job_id"]
    candidate_ids = state.get("candidate_ids", [])
    session_id = state["session_id"]
    user_id = state.get("user_id")   # 从状态中获取用户ID

    if not candidate_ids:
        logger.warning("No candidates from rough screening, skip fine screening")
        return {**state, "fine_reports": [], "current_step": "fine_done"}

    try:
        engine = FineScreeningEngine(tenant_id, job_id)
        reports = await engine.screen_candidates(candidate_ids, session_id, user_id=user_id)
        fine_reports = [report.dict() for report in reports]
        logger.info(f"Fine screening completed, {len(fine_reports)} reports")
    except Exception as e:
        logger.error(f"Fine screening failed: {e}")
        fine_reports = []

    return {
        **state,
        "fine_reports": fine_reports,
        "current_step": "fine_done"
    }