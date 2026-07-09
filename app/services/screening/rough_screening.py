from app.infrastructure.llm_client import LLMClient
from app.infrastructure.models.embedding_client import embed_texts
from app.infrastructure.chroma_client import get_collection
from app.infrastructure.models.reranker_client import rerank as rerank_model
from app.services.screening.hard_filter import get_filtered_candidate_ids
from app.services.screening.bm25_index import BM25Index
from app.core.constants import DEFAULT_RAG_TOP_K, DEFAULT_RERANK_THRESHOLD
from app.db.repositories.job_repository import JobRepository
from app.db.session import get_db
import logging

logger = logging.getLogger(__name__)

async def hyde_query_rewrite(query: str) -> str:
    llm = LLMClient()
    prompt = f"基于以下查询，生成一份理想的候选人简历片段，用于检索：\n{query}"
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    return resp.choices[0].message.content

def dense_retrieval(query_embedding, tenant_id: str, top_k=DEFAULT_RAG_TOP_K):
    collection = get_collection("resumes")
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"tenant_id": tenant_id},
        include=["documents", "metadatas", "distances"]
    )
    # 整理为 [{"candidate_id": ..., "chunk": ..., "score": ...}]
    output = []
    for i, (doc, meta, dist) in enumerate(zip(results['documents'][0], results['metadatas'][0], results['distances'][0])):
        output.append({
            "candidate_id": meta['candidate_id'],
            "chunk": doc,
            "score": 1 - dist  # Chroma返回distance，转为相似度
        })
    return output

def sparse_retrieval(query: str, candidate_ids: list, bm25: BM25Index, top_k=DEFAULT_RAG_TOP_K):
    # 假设bm25.index是按照所有简历构建的，但我们只需要在candidate_ids范围内检索
    # 简化：先构建一个子索引或后过滤
    results = bm25.search(query, top_k=top_k)
    # 过滤出在候选ID中的结果（candidate_ids为UUID list，但bm25索引的是文档文本，需建立映射）
    # 实际实现中，bm25应该以candidate_id为键，这里为演示简化
    return [{"candidate_id": "id_from_index", "score": score} for _ , score in results]

def reciprocal_rank_fusion(dense_results, sparse_results, k=60):
    scores = {}
    for rank, item in enumerate(dense_results):
        doc_id = item['candidate_id']
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
    for rank, item in enumerate(sparse_results):
        doc_id = item['candidate_id']
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
    sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [id for id, _ in sorted_ids]

async def self_rag_check(query: str, documents: list) -> bool:
    llm = LLMClient()
    combined = "\n".join([d['chunk'][:200] for d in documents[:5]])
    prompt = f"查询：{query}\n\n检索到的文档片段：\n{combined}\n\n这些片段是否足以回答查询？仅回复“是”或“否”。"
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    return resp.choices[0].message.content.strip().lower() == "是"