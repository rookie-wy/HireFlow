"""筛选 API：NDJSON 流式返回。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.security import require_internal_key
from app.services.screening.orchestrator import run_screening

router = APIRouter(dependencies=[Depends(require_internal_key)])


@router.post("/screening/run")
async def screening_run(payload: dict):
    """完整筛选（粗筛 + 圆桌精筛），NDJSON 事件流。"""
    return StreamingResponse(
        run_screening(payload),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
