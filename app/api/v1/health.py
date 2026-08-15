from fastapi import APIRouter
from app.db.session import get_db
from app.infrastructure.redis_client import get_redis
from app.infrastructure.chroma_client import get_chroma_client

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查：探测数据库 / Redis / ChromaDB 连通性。"""
    checks = {}

    # 数据库
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    # Redis
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    # ChromaDB
    try:
        get_chroma_client().heartbeat()
        checks["chroma"] = "ok"
    except Exception:
        checks["chroma"] = "unavailable"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "service": "ai-recruitment-agent", "checks": checks}
