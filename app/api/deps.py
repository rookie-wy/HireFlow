from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_access_token
from app.core.context import tenant_id_var
from app.models.enums import UserRole

security = HTTPBearer()

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Token missing tenant_id")
    request.state.user_id = payload.get("user_id")
    request.state.tenant_id = tenant_id
    request.state.role = payload.get("role")
    # 设置租户上下文，供 Repository 层做数据隔离
    tenant_id_var.set(tenant_id)
    return payload

def require_role(role: UserRole):
    async def role_checker(request: Request):
        if getattr(request.state, "role", None) != role.value:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return True
    return role_checker