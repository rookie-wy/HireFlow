import asyncio
import logging
from app.infrastructure.llm_client import LLMClient
from app.infrastructure.models.embedding_client import embed_texts
from app.infrastructure.chroma_client import get_collection
from app.infrastructure.models.reranker_client import rerank as rerank_model
from app.services.screening.hard_filter import get_filtered_candidate_ids
from app.services.screening.bm25_index import BM25Index
from app.core.constants import DEFAULT_RAG_TOP_K, DEFAULT_RERANK_THRESHOLD
from app.db.repositories.job_repository import JobRepository
from app.db.session import get_db

logger = logging.getLogger(__name__)

async def hyde_query_rewrite(query: str) -> str:
    llm = LLMClient()
    prompt = f"基于以下查询，生成一份理想的候选人简历片段：\n{query}"
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
    output = []
    for doc, meta, dist in zip(results['documents'][0], results['metadatas'][0], results['distances'][0]):
        output.append({
            "candidate_id": meta['candidate_id'],
            "chunk": doc,
            "score": 1 - dist
        })
    return output

def sparse_retrieval(query: str, bm25: BM25Index, top_k=DEFAULT_RAG_TOP_K):
    if not bm25:
        return []
    results = bm25.search(query, top_k=top_k)
    return [{"candidate_id": f"bm25_{i}", "score": score} for i, score in results]

def reciprocal_rank_fusion(dense_results, sparse_results, k=60):
    scores = {}
    for rank, item in enumerate(dense_results):
        scores[item['candidate_id']] = scores.get(item['candidate_id'], 0) + 1 / (k + rank)
    for rank, item in enumerate(sparse_results):
        scores[item['candidate_id']] = scores.get(item['candidate_id'], 0) + 1 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)

async def self_rag_check(query: str, documents: list) -> bool:
    llm = LLMClient()
    combined = "\n".join([d['chunk'][:200] for d in documents[:5]])
    prompt = f"查询：{query}\n\n检索到的文档片段：\n{combined}\n\n这些片段是否足以回答查询？仅回复“是”或“否”。"
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    return resp.choices[0].message.content.strip().lower() == "是"

class HybridScreener:
    def __init__(self, tenant_id: str, job_id: str):
        self.tenant_id = tenant_id
        self.job_id = job_id

    async def screen(self, query: str, max_candidates=10, enable_hyde=True):
        # 1. 硬性过滤
        with get_db() as conn:
            job_repo = JobRepository(conn)
            job = job_repo.find_by_id(self.job_id)
            hard_reqs = job.jd_json.get("hard_requirements", []) if job and job.jd_json else []
        filtered_ids = get_filtered_candidate_ids(self.tenant_id, self.job_id, hard_reqs)
        if not filtered_ids:
            return {"session_id": "temp", "results": [], "trace_id": ""}

        # 2. 查询改写（HyDE 可选）
        search_query = query
        if enable_hyde:
            try:
                search_query = await hyde_query_rewrite(query)
            except Exception as e:
                logger.warning(f"HyDE rewrite failed: {e}")

        # 3. 稠密检索（安全调用嵌入）
        dense_res = []
        try:
            emb = embed_texts([search_query])
            if emb:
                dense_res = dense_retrieval(emb[0], self.tenant_id)
        except Exception as e:
            logger.warning(f"Dense retrieval failed: {e}")

        # 4. 稀疏检索（BM25 降级）
        sparse_res = []
        try:
            bm25 = BM25Index()
            # 实际应加载过滤后的简历文本构建索引，此处简化
            sparse_res = sparse_retrieval(query, bm25)
        except Exception as e:
            logger.warning(f"Sparse retrieval failed: {e}")

        # 5. RRF 融合
        fused = reciprocal_rank_fusion(dense_res, sparse_res)[:max_candidates * 2]

        # 6. 准备重排序文档
        docs_to_rerank = []
        for item in dense_res:
            if item['candidate_id'] in fused:
                docs_to_rerank.append(item['chunk'])

        # 7. 重排序
        top_n = []
        if docs_to_rerank:
            try:
                scores = rerank_model(query, docs_to_rerank)
                filtered = [(doc, score) for doc, score in zip(docs_to_rerank, scores) if score >= DEFAULT_RERANK_THRESHOLD]
                filtered.sort(key=lambda x: x[1], reverse=True)
                top_n = filtered[:max_candidates]
            except Exception as e:
                logger.warning(f"Rerank failed: {e}")

        # 8. Self-RAG 反思（可选）
        try:
            if top_n:
                sufficient = await self_rag_check(query, [{"chunk": doc} for doc, _ in top_n])
                if not sufficient:
                    logger.info("Self-RAG suggests evidence insufficient")
        except Exception as e:
            logger.warning(f"Self-RAG failed: {e}")

        results = [{"candidate_id": "unknown", "score": score, "reasons": [], "evidence": [doc[:100]]} for doc, score in top_n]
        return {"session_id": "session_temp", "results": results, "trace_id": "trace_temp"}