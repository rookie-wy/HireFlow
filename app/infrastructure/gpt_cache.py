from gptcache import Cache
from gptcache.manager import manager_factory
from gptcache.processor.pre import last_content
from gptcache.embedding import Onnx
from gptcache.similarity_evaluation import SbertCrossencoderEvaluation
import hashlib

_cache = None

def init_gpt_cache():
    global _cache
    if _cache is None:
        # 缓存存储使用Redis，向量存储使用本地
        _cache = Cache()
        _cache.init(
            pre_embedding_func=last_content,
            embedding_func=Onnx(),
            similarity_evaluation=SbertCrossencoderEvaluation(),
            data_manager=manager_factory("redis,faiss", data_dir="./gptcache_data", redis_host="redis"),
        )
    return _cache

def get_cache_key(jd_summary_hash: str, candidate_id: str) -> str:
    raw = f"{jd_summary_hash}:{candidate_id}"
    return hashlib.md5(raw.encode()).hexdigest()