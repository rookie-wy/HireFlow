from fastapi import APIRouter, Depends, Request, HTTPException
from app.api.deps import get_current_user
from app.core.response import APIResponse, success
from app.agents.graph import app as agent_app
from pydantic import BaseModel

router = APIRouter()

class SendInterviewRequest(BaseModel):
    session_id: str
    candidate_id: str
    proposed_times: list[str]  # ["2025-03-20T10:00:00Z", ...]

@router.post("/interview/send", response_model=APIResponse)
async def send_interview(req: SendInterviewRequest, request: Request, user=Depends(get_current_user)):
    # 该接口用于HR确认发送，实际应通过状态图继续执行
    # 但文档定义为一个单独端点，需兼容两种方式：
    # 方式1：继续暂停的图
    config = {"configurable": {"thread_id": req.session_id}}
    try:
        # 更新状态设置确认标志
        agent_app.update_state(config, {"interview_confirmed": True, "candidate_ids": [req.candidate_id]})
        final_state = await agent_app.ainvoke(None, config)
        return success(data={"status": "sent", "session_id": req.session_id})
    except Exception as e:
        # 若图未暂停，则直接调用调度服务（略）
        raise HTTPException(status_code=400, detail=str(e))