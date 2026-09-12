"""ChromaDB 客户端（Python 服务独占的向量存储）。"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import chromadb

from app.core.config import get_settings
from app.core.errors import get_logger

log = get_logger(__name__)

COLLECTION_RESUMES = "resumes"
COLLECTION_INTERACTION_SUMMARIES = "interaction_summaries"

VECTOR_DIM = 1024  # BGE-M3 dense；MiniLM 后备时维度自动适配 collection

_client: Optional[chromadb.HttpClient] = None
_client_lock = threading.Lock()
_collections: Dict[str, Any] = {}


def get_chroma() -> chromadb.HttpClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                s = get_settings()
                _client = chromadb.HttpClient(host=s.chroma_host, port=s.chroma_port)
    return _client


def get_collection(name: str):
    if name not in _collections:
        client = get_chroma()
        _collections[name] = client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )
    return _collections[name]


def reset_collections_cache() -> None:
    """连接重建后清空 collection 缓存。"""
    global _client
    with _client_lock:
        _client = None
    _collections.clear()


def upsert_resumes(
    candidate_id: str,
    tenant_id: str,
    chunks: List[str],
    vectors: List[List[float]],
) -> int:
    """写入/覆盖候选人简历分块向量，返回写入块数。"""
    if not chunks:
        return 0
    coll = get_collection(COLLECTION_RESUMES)
    # 先清旧块（同名 candidate 重传时避免脏数据）
    try:
        coll.delete(where={"$and": [{"tenant_id": tenant_id}, {"candidate_id": candidate_id}]})
    except Exception:  # noqa: BLE001 首次写入时无旧数据
        pass
    ids = [f"{candidate_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {"tenant_id": tenant_id, "candidate_id": candidate_id, "chunk_index": i}
        for i in range(len(chunks))
    ]
    coll.upsert(ids=ids, documents=chunks, embeddings=vectors, metadatas=metadatas)
    return len(chunks)


def delete_candidate_vectors(tenant_id: str, candidate_id: str) -> None:
    coll = get_collection(COLLECTION_RESUMES)
    try:
        coll.delete(where={"$and": [{"tenant_id": tenant_id}, {"candidate_id": candidate_id}]})
    except Exception:  # noqa: BLE001
        log.warning("delete vectors failed for candidate %s", candidate_id)


def query_resumes(
    tenant_id: str,
    query_vector: List[float],
    top_k: int,
) -> List[dict]:
    """租户隔离的稠密检索，返回 [{candidate_id, chunk, distance}]。"""
    coll = get_collection(COLLECTION_RESUMES)
    result = coll.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, coll.count() or 1),
        where={"tenant_id": tenant_id},
        include=["documents", "metadatas", "distances"],
    )
    hits: List[dict] = []
    if not result["ids"] or not result["ids"][0]:
        return hits
    for i, doc_id in enumerate(result["ids"][0]):
        meta = (result["metadatas"][0] or [{}])[i] or {}
        distance = (result["distances"][0] or [0.0])[i]
        hits.append(
            {
                "candidate_id": meta.get("candidate_id", ""),
                "chunk": (result["documents"][0] or [""])[i] or "",
                "distance": float(distance),
                "score": 1.0 - float(distance),
            }
        )
    return hits


def upsert_interaction_summary(
    summary_id: str,
    tenant_id: str,
    text: str,
    vector: List[float],
    target_id: str,
    event_type: str,
) -> None:
    coll = get_collection(COLLECTION_INTERACTION_SUMMARIES)
    coll.upsert(
        ids=[summary_id],
        documents=[text],
        embeddings=[vector],
        metadatas=[{"tenant_id": tenant_id, "target_id": target_id, "event_type": event_type}],
    )
