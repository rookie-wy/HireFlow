from app.agents.state import AgentState
from app.services.parsing.jd_parser import parse_jd, save_job_to_db
import uuid

async def parse_jd_node(state: AgentState) -> AgentState:
    tenant_id = state["tenant_id"]
    jd_text = state["job_text"]
    if not jd_text:
        return {**state, "current_step": "no_jd"}
    parsed = await parse_jd(jd_text)
    job = save_job_to_db(tenant_id, jd_text, parsed)
    return {
        **state,
        "job_id": job.id,
        "parsed_jd": parsed.model_dump(),
        "current_step": "parse_jd_done"
    }