"""重排策略：默认用 BGE-M3 向量余弦（快），可选 Cross-Encoder（准但 CPU 上很慢）。

实测（本机 CPU，200 字查询 + 280/207 字文档）：
  - BGE-reranker-v2-m3（cross-encoder）：2 对 6.4s ≈ 3.2s/对；10 对 20s+；
    30 对会把粗筛拖到 60s 以上，直接顶穿 backend 的 90s 客户端超时。
  - BGE-M3 向量余弦：一次批量编码（与简历向量同一模型，已常驻）≈ 每对 30–80ms。

因此在 CPU 部署下默认走向量重排；有 GPU 或对精度极敏感时用 RERANK_MODE=cross_encoder。
"""
from __future__ import annotations

import contextvars
import math
from typing import List, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.core.errors import get_logger
from app.infra import embedding_client

log = get_logger(__name__)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def rerank_by_cosine(query: str, documents: List[str]) -> Optional[List[float]]:
    """向量余弦重排：把查询与文档一起编码（一次批量调用），返回 [0,1] 归一化分数。"""
    if not documents:
        return []
    vectors = embedding_client.embed_texts([query] + list(documents))
    if not vectors or len(vectors) != len(documents) + 1:
        return None
    qv, dvs = vectors[0], vectors[1:]
    # 余弦相似度映射到 [0,1]，与 cross-encoder 的 sigmoid 分数同量纲，便于共用阈值
    return [round((_cosine(qv, dv) + 1.0) / 2.0, 6) for dv in dvs]


# 当前筛选会话的岗位级覆盖（O7）。用 contextvars 而不是全局变量：
# 多个筛选任务可能并发跑在不同线程里，全局变量会互相串味。
_session_overrides: "contextvars.ContextVar[dict]" = contextvars.ContextVar(
    "screen_overrides", default={}
)


def apply_overrides(overrides: Optional[dict]) -> "contextvars.Token":
    """设置本次筛选会话的参数覆盖，返回 token 供 reset。"""
    return _session_overrides.set(dict(overrides or {}))


def reset_overrides(token: "contextvars.Token") -> None:
    _session_overrides.reset(token)


def effective_mode() -> str:
    """当前生效的重排模式：岗位覆盖优先，其次全局配置。"""
    override = _session_overrides.get({})
    return str(override.get("rerank_mode") or get_settings().rerank_mode or "cosine").lower()


def rerank_documents(query: str, documents: List[str]) -> Optional[List[float]]:
    """按配置选择重排策略。返回 None 表示重排不可用（调用方回退 RRF 分）。"""
    if not documents:
        return []
    mode = effective_mode()
    if mode == "cross_encoder":
        scores = embedding_client.rerank_query_docs(query, documents)  # 懒加载（未预热时首次调用会加载）
        if scores is not None:
            return scores
        log.warning("cross_encoder rerank unavailable, fallback to cosine")
    return rerank_by_cosine(query, documents)


def mode_name() -> str:
    return (get_settings().rerank_mode or "cosine").lower()


def describe() -> Tuple[str, int]:
    """返回 (策略名, 送入对数系数)，便于日志与前端展示。"""
    s = get_settings()
    return mode_name(), s.rerank_pairs_factor
