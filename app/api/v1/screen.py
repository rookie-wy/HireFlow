from fastapi import APIRouter, Depends, Request, HTTPException
from app.api.deps import get_current_user
from app.core.response import APIResponse, success
from app.agents.graph import app as agent_app
from app.core.limiter import limiter
from pydantic import BaseModel, Field
from typing import Optional
import uuid
import logging

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

class ScreenRequest(BaseModel):
    job_id: str = Field(..., description="岗位ID")
    query: Optional[str] = Field(default="", description="自然语言查询或额外要求")
    max_candidates: int = Field(default=10, ge=1, le=50, description="最大返回候选人数")
    session_id: Optional[str] = Field(default=None, description="会话ID，用于恢复流程")

@router.post("/screen", response_model=APIResponse)
@limiter.limit("5/minute")
async def screen_candidates(req: ScreenRequest, request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    user_id = user.get("user_id")
    session_id = req.session_id or str(uuid.uuid4())   # 如果没有 session_id 则生成新会话
    trace_id = request.state.trace_id

    # 构建初始状态（根据当前 Agent 状态机的需要）
    initial_state = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "job_id": req.job_id,
        "job_text": "",                # 如果流程中需要原始JD文本，可以从数据库读取后填入
        "messages": [{"role": "user", "content": req.query}],
        "current_step": "start",
        "candidate_ids": [],
        "rough_results": [],
        "fine_reports": [],
        "interview_draft": None,
        "interview_confirmed": False,
        "feedback": None,
    }

    # recursion_limit 限制图执行步数，防止死循环 / 失控超时
    config = {"configurable": {"thread_id": session_id, "tenant_id": tenant_id}, "recursion_limit": 50}
    try:
        final_state = await agent_app.ainvoke(initial_state, config)
        results = final_state.get("fine_reports", [])
        # 简化：直接返回结果，实际可根据流程状态返回中间状态
        return success(data={
            "session_id": session_id,
            "results": results,
            "trace_id": trace_id
        })
    except Exception as e:
        logger.exception(f"Screen agent error: {e}")
        raise HTTPException(status_code=500, detail="Agent execution failed")
from app.db.repositories.match_repository import MatchRepository

@router.get("/match_results", response_model=APIResponse)
async def get_match_results(job_id: str, request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    with get_db() as conn:
        repo = MatchRepository(conn)
        results = repo.list_by_job(job_id)
        return success(data=results)