from FlagEmbedding import FlagReranker

from app.core.config import settings

_reranker = None

def get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = FlagReranker('BAAI/bge-reranker-v2-m3',
                                 use_fp16=True,
                                 device=settings.RERANKER_DEVICE)
    return _reranker

def rerank(query: str, documents: list) -> list:
    model = get_reranker()
    pairs = [[query, doc] for doc in documents]
    scores = model.compute_score(pairs)
    return scores