"""AI招聘Agent — AI能力服务入口。

职责：LLM 调用、文档解析、嵌入与向量检索、混合粗筛、多Agent圆桌讨论精筛。
边界：不直连 MySQL；业务数据由 backend 经请求传入；仅写 ChromaDB。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import health, interview, parsing, screening
from app.core.config import get_settings
from app.core.errors import AgentError, get_logger, setup_logging
from app.core.security import trace_middleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    s = get_settings()
    # 后台预热嵌入/重排模型：首次上传简历的数十秒冷启动不再落在请求路径上。
    # 放后台线程且不阻塞启动，/healthz 的 checks.embedder 可观测就绪状态。
    if s.warmup_models:
        from app.infra.embedding_client import warmup

        asyncio.get_running_loop().run_in_executor(None, warmup)
        log.info("model warmup scheduled in background")
    yield


settings = get_settings()

app = FastAPI(
    title="Recruitment Agent Service",
    version="5.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.app_env == "production" else None,
)

app.middleware("http")(trace_middleware)

app.include_router(health.router, prefix="/healthz", tags=["health"])
app.include_router(parsing.router, prefix="", tags=["parsing"])
app.include_router(screening.router, prefix="", tags=["screening"])
app.include_router(interview.router, prefix="", tags=["interview"])
# 面试调度路由在 Phase 8 挂载


@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.core.errors import get_logger

    get_logger(__name__).exception("unhandled error")
    return JSONResponse(status_code=500, content={"code": 50000, "message": "服务内部错误"})
