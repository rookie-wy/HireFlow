from fastapi import APIRouter, Depends, Request
from app.api.deps import get_current_user
from app.models.schemas.job_schema import JobCreateRequest
from app.services.parsing.jd_parser import parse_jd, save_job_to_db
from app.core.response import APIResponse, success
from app.db.repositories.job_repository import JobRepository
from app.db.session import get_db


router = APIRouter()

@router.post("/jobs", response_model=APIResponse)
async def create_job(req: JobCreateRequest, request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    parsed_jd = await parse_jd(req.jd_text)
    job = save_job_to_db(tenant_id, req.jd_text, parsed_jd)
    return success(data={"job_id": job.id, "parsed": parsed_jd.model_dump()})
@router.get("/jobs", response_model=APIResponse)
async def list_jobs(request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    with get_db() as conn:
        repo = JobRepository(conn)
        jobs = repo.list_all()
        data = []
        for job in jobs:
            data.append({
                "job_id": job.id,
                "title": job.title,
                "category": job.job_category,
                "hard_requirements": job.jd_json.get("hard_requirements", []) if job.jd_json else [],
                "soft_requirements": job.jd_json.get("soft_requirements", []) if job.jd_json else [],
                "created_at": job.created_at.isoformat() if job.created_at else None
            })
        return success(data=data)