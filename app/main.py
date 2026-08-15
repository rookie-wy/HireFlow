import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.v1 import health, jobs, candidates, screen, interview, auth, feedback
from app.api.deps import get_current_user
from app.api.exception_handlers import app_exception_handler, general_exception_handler
from app.core.exceptions import AppException
from app.core.config import settings
from app.core.logging_config import setup_logging, trace_id_var
from app.core.limiter import limiter
from app.db.session import init_pool, close_pool
from app.infrastructure.redis_client import close_redis


setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化数据库连接池并建表
    init_pool()
    yield
    # 关闭：释放连接池与 Redis 连接
    close_pool()
    close_redis()


app = FastAPI(title="AI Recruitment Agent", version="3.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS：限定来源，避免全开
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    trace_id_var.set(trace_id)
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


# 注册全局异常处理
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册路由
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(candidates.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(screen.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(interview.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(feedback.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
