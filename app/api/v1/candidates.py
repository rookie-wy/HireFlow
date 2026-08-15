from fastapi import APIRouter, UploadFile, File, Depends, Request, HTTPException
from app.api.deps import get_current_user
from app.db.repositories.candidate_repository import CandidateRepository
from app.db.session import get_db
from app.services.parsing.resume_parser import process_resume_upload
from app.core.response import APIResponse, success
from app.core.config import settings
from app.core.limiter import limiter
import os
router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

# 魔数（文件签名）校验，防止伪造扩展名绕过白名单
_MAGIC_SIGNATURES = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}


def _verify_file_signature(content: bytes, ext: str) -> bool:
    magic = _MAGIC_SIGNATURES.get(ext)
    if magic is None:
        return False
    return content[: len(magic)] == magic

@router.post("/candidates/upload", response_model=APIResponse)
@limiter.limit("20/minute")
async def upload_resume(
    file: UploadFile = File(...),
    request: Request = None,
    user=Depends(get_current_user)
):
    # 文件类型检查
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    # 大小限制 (10MB)
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
    # 内容签名校验（防止伪造扩展名绕过白名单）
    if not _verify_file_signature(content, ext):
        raise HTTPException(status_code=400, detail="File content does not match extension")
    tenant_id = request.state.tenant_id
    profile = await process_resume_upload(content, file.filename, tenant_id)
    return success(data={"candidate_id": profile.email, "profile": profile.model_dump()})
@router.get("/candidates", response_model=APIResponse)
async def list_candidates(request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    with get_db() as conn:
        repo = CandidateRepository(conn)
        candidates = repo.list_by_tenant()
        # 返回简化的候选人信息列表
        data = []
        for c in candidates:
            data.append({
                "candidate_id": c.id,
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "skills": c.structured_json.get("skills", []) if c.structured_json else [],
                "created_at": c.created_at.isoformat() if c.created_at else None
            })
        return success(data=data)

@router.delete("/candidates/{candidate_id}", response_model=APIResponse)
async def delete_candidate(candidate_id: str, request: Request, user=Depends(get_current_user)):
    tenant_id = request.state.tenant_id
    with get_db() as conn:
        repo = CandidateRepository(conn)
        existing = repo.find_by_id(candidate_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Candidate not found")
        repo.delete(candidate_id)   # 需要在 Repository 中实现 delete 方法
    return success(data={"candidate_id": candidate_id, "status": "deleted"})