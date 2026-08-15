from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from app.agents.state import AgentState
from app.agents.nodes.parse_jd import parse_jd_node
from app.agents.nodes.rough_screening import rough_screening_node
from app.agents.nodes.fine_screening import fine_screening_node
from app.agents.nodes.schedule import schedule_node
from app.agents.nodes.feedback import feedback_node

# 条件路由函数
def should_continue_after_rough(state: AgentState) -> str:
    if state.get("rough_results"):
        return "fine_screening"
    return END

def after_fine(state: AgentState) -> str:
    if state.get("fine_reports"):
        return "schedule"
    return END

def after_schedule(state: AgentState) -> str:
    if not state.get("interview_confirmed"):
        return "handle_feedback"  # 重命名后的节点
    return END

# 构建图
builder = StateGraph(AgentState)

# 添加节点，注意反馈节点使用新名称
builder.add_node("parse_jd", parse_jd_node)
builder.add_node("rough_screening", rough_screening_node)
builder.add_node("fine_screening", fine_screening_node)
builder.add_node("schedule", schedule_node)
builder.add_node("handle_feedback", feedback_node)  # 关键修改：节点名改为 handle_feedback

# 设置流程
builder.set_entry_point("parse_jd")
builder.add_edge("parse_jd", "rough_screening")
builder.add_conditional_edges("rough_screening", should_continue_after_rough)
builder.add_conditional_edges("fine_screening", after_fine)
builder.add_edge("fine_screening", "schedule")
builder.add_conditional_edges("schedule", after_schedule)
builder.add_edge("handle_feedback", END)  # 反馈后结束

# 编译
# 注意：MemorySaver 为单进程内存态 checkpoint，进程重启后会话历史丢失。
# 企业多副本/长期运行应替换为 SqliteSaver / RedisSaver（需额外安装
# langgraph-checkpoint-sqlite / langgraph-checkpoint-redis 包），此处保持内存实现。
memory = MemorySaver()
app = builder.compile(checkpointer=memory, interrupt_before=["schedule"])