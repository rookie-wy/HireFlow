from typing import TypedDict, List, Optional, Dict, Any
from langgraph.graph import MessagesState

class AgentState(TypedDict):
    messages: List[Dict]          # 聊天消息历史
    tenant_id: str
    user_id: str
    session_id: str
    trace_id: str
    job_id: Optional[str]
    job_text: Optional[str]       # 原始JD文本
    parsed_jd: Optional[Dict]     # 解析后的JD
    candidate_ids: List[str]      # 当前候选池
    rough_results: List[Dict]     # 粗筛结果（含分数等）
    fine_reports: List[Dict]      # 精筛报告
    interview_draft: Optional[Dict]
    interview_confirmed: bool
    feedback: Optional[str]       # HR反馈
    current_step: str             # 当前步骤标识
    # 其他临时状态