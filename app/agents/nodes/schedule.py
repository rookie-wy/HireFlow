from app.services.scheduling.interview_scheduler import InterviewScheduler
from app.agents.state import AgentState

async def schedule_node(state: AgentState) -> AgentState:
    # 如果已有确认标记，执行发送
    if state.get("interview_confirmed"):
        scheduler = InterviewScheduler(state["tenant_id"])
        # 这里需要从状态获取draft和选择的时间等，略
        # await scheduler.confirm_and_send(...)
        return {**state, "current_step": "schedule_sent"}
    # 否则生成草稿并暂停，等待人工确认
    # scheduler = ...
    # draft = await scheduler.generate_draft(...)
    return {
        **state,
        "interview_draft": {},  # 实际draft内容
        "current_step": "wait_hr_confirm"
    }