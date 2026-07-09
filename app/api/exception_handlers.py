from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.exceptions import AppException
from app.core.response import error
import logging

logger = logging.getLogger(__name__)

async def app_exception_handler(request: Request, exc: AppException):
    trace_id = getattr(request.state, "trace_id", "")
    logger.error(f"Exception: {exc.message}", extra={"trace_id": trace_id, "code": exc.code})
    return JSONResponse(
        status_code=exc.http_status,
        content=error(code=exc.code, message=exc.message, trace_id=trace_id).dict()
    )

async def general_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "")
    logger.exception(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content=error(code=50000, message="Internal server error", trace_id=trace_id).dict()
    )