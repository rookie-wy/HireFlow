"""内部鉴权：X-Internal-Key 校验 + trace_id 中间件。"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.core.errors import set_trace_id

INTERNAL_KEY_HEADER = "X-Internal-Key"
TRACE_HEADER = "X-Trace-Id"


async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex
    set_trace_id(trace_id)
    response = await call_next(request)
    response.headers[TRACE_HEADER] = trace_id
    return response


async def require_internal_key(request: Request) -> None:
    """服务间鉴权依赖；/healthz 已在路由级别豁免。"""
    settings = get_settings()
    if request.headers.get(INTERNAL_KEY_HEADER) != settings.agent_internal_key:
        raise HTTPException(status_code=401, detail={"code": 40100, "message": "invalid internal key"})
