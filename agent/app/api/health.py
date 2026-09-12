"""健康检查路由（无需内部密钥）。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.metrics import render_prometheus

router = APIRouter()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus 文本格式指标（进程内注册表，零依赖）。"""
    return render_prometheus()


@router.get("")
async def healthz() -> dict:
    """存活 + 依赖状态。懒加载组件按需探测，未加载不阻塞、不抛错。"""
    checks: dict = {"llm_config": True}

    try:
        from app.infra import llm_client

        llm_client.get_llm_client()
    except Exception:  # noqa: BLE001
        checks["llm_config"] = "fail"

    try:
        from app.infra import chroma_client

        chroma_client.get_chroma().heartbeat()
        checks["chroma"] = "ok"
    except Exception:  # noqa: BLE001 未安装或未启动均视为未就绪
        checks["chroma"] = "fail"

    # 模型就绪状态（预热后为 true，便于区分"服务活着但模型没加载完"）
    try:
        from app.infra import embedding_client

        checks["embedder"] = embedding_client.embedder_ready()
    except Exception:  # noqa: BLE001
        checks["embedder"] = "fail"

    status = "ok" if all(v == "ok" or v is True for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks, "service": "agent"}
