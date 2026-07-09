import uuid
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.v1 import health, jobs, candidates, screen, interview
from app.api.deps import get_current_user
from app.api.exception_handlers import app_exception_handler, general_exception_handler
from app.core.exceptions import AppException
from app.core.logging_config import setup_logging, trace_id_var
from app.api.v1 import feedback

setup_logging()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="AI Recruitment Agent", version="3.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS (允许开发用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(jobs.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(candidates.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(screen.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(interview.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(feedback.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)