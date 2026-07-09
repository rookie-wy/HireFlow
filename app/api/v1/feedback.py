from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from app.api.deps import get_current_user
from app.core.response import APIResponse, success
from app.services.feedback.feedback_handler import process_feedback

router = APIRouter()

class FeedbackRequest(BaseModel):
    candidate_id: str = Field(..., description="候选人ID")
    job_id: str = Field(..., description="岗位ID")
    feedback: str = Field(..., description="反馈类型: suitable / not_suitable / pending")
    session_id: str = Field(default="", description="会话ID")

@router.post("/feedback", response_model=APIResponse)
async def submit_feedback(req: FeedbackRequest, request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    user_id = request.state.user_id
    process_feedback(
        tenant_id=tenant_id,
        user_id=user_id,
        candidate_id=req.candidate_id,
        feedback=req.feedback,
        session_id=req.session_id
    )
    return success(data={"status": "ok"})