from app.services.screening.hybrid_screener import HybridScreener
from app.agents.state import AgentState

async def rough_screening_node(state: AgentState) -> AgentState:
    tenant_id = state["tenant_id"]
    job_id = state["job_id"]
    query = state.get("messages", [{}])[-1].get("content", "")  # 假设最后一条消息为用户查询
    screener = HybridScreener(tenant_id, job_id)
    res = await screener.screen(query, max_candidates=10)
    return {
        **state,
        "rough_results": res.get("results", []),
        "candidate_ids": [r["candidate_id"] for r in res.get("results", [])],
        "current_step": "rough_done"
    }