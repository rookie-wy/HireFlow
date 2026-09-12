"""向量化：滑窗分块 + BGE-M3 嵌入 + Chroma 写入。"""
from __future__ import annotations

from typing import List

from app.core.config import get_settings
from app.core.errors import get_logger
from app.infra import chroma_client, embedding_client

log = get_logger(__name__)


def chunk_text(text: str, chunk_size: int = 0, overlap: int = 0) -> List[str]:
    s = get_settings()
    chunk_size = chunk_size or s.chunk_size
    overlap = overlap if overlap is not None else s.chunk_overlap
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    step = max(chunk_size - overlap, 1)
    for i in range(0, len(text), step):
        piece = text[i : i + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if i + chunk_size >= len(text):
            break
    return chunks


def vectorize_candidate(candidate_id: str, tenant_id: str, resume_text: str) -> int:
    """分块嵌入并写入 Chroma resumes collection，返回写入块数。

    嵌入失败时抛 UpstreamError（调用方决定是否降级）。
    """
    chunks = chunk_text(resume_text)
    if not chunks:
        return 0
    vectors = embedding_client.embed_texts(chunks)
    if vectors is None:
        from app.core.errors import UpstreamError

        raise UpstreamError("嵌入服务不可用，无法向量化简历")
    written = chroma_client.upsert_resumes(
        candidate_id=candidate_id, tenant_id=tenant_id, chunks=chunks, vectors=vectors
    )
    log.info("vectorized candidate=%s chunks=%d", candidate_id, written)
    return written
