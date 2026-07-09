from app.services.feedback.feedback_handler import process_feedback
from app.agents.state import AgentState

async def feedback_node(state: AgentState) -> AgentState:
    if state.get("feedback"):
        process_feedback(
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            candidate_id=state.get("candidate_ids", [None])[0],
            feedback=state["feedback"],
            session_id=state["session_id"]
        )
    return {**state, "current_step": "feedback_done"}