import hashlib
import logging

logger = logging.getLogger(__name__)

try:
    from gptcache import Cache
    from gptcache.manager import manager_factory
    from gptcache.processor.pre import last_content
    from gptcache.embedding import Onnx
    from gptcache.similarity_evaluation import SbertCrossencoderEvaluation
    GPTCACHE_AVAILABLE = True
except ImportError:  # gptcache 未安装（后置项），LLM 结果缓存退化为禁用
    GPTCACHE_AVAILABLE = False

_cache = None


def init_gpt_cache():
    global _cache
    if _cache is None:
        if not GPTCACHE_AVAILABLE:
            logger.warning("gptcache 未安装，LLM 结果缓存已禁用")
            return None
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
