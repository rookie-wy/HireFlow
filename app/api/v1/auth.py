"""认证端点：注册与登录，签发 JWT。

注意：登录/注册为纯同步的数据库 + 密码哈希操作，使用同步 def 端点，
让 FastAPI 放入线程池执行，避免阻塞事件循环（bcrypt 为 CPU 密集）。
"""
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.core.response import APIResponse, success
from app.db.repositories.user_repository import UserRepository
from app.db.session import get_db
from app.models.domain.user import User

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(default="hr", max_length=32)


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: str


@router.post("/auth/register", response_model=APIResponse)
def register(req: RegisterRequest):
    # 生产环境注册应受管理员权限保护，这里仅作为最小可用闭环开放
    with get_db() as conn:
        repo = UserRepository(conn)
        if repo.find_by_username(req.username, req.tenant_id):
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=req.tenant_id,
            username=req.username,
            role=req.role,
            password_hash=hash_password(req.password),
        )
        repo.insert(user)
    return success(data={"username": req.username, "tenant_id": req.tenant_id})


@router.post("/auth/login", response_model=APIResponse)
@limiter.limit("10/minute")
def login(req: LoginRequest, request: Request):
    with get_db() as conn:
        repo = UserRepository(conn)
        user = repo.find_by_username(req.username, req.tenant_id)
        if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_access_token({
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "role": user.role,
        })
    return success(data={
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
    })
