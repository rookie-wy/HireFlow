import logging
import os
from typing import Optional, List

logger = logging.getLogger(__name__)

_embedding_model: Optional[object] = None
_model_name: Optional[str] = None

def get_embedding_model() -> Optional[object]:
    """
    尝试加载 BGE-M3，失败则加载轻量 MiniLM 模型。
    """
    global _embedding_model, _model_name
    if _embedding_model is not None:
        return _embedding_model

    # 1. 尝试 BGE-M3
    try:
        from FlagEmbedding import BGEM3FlagModel
        model_path = os.getenv("BGE_MODEL_PATH", "BAAI/bge-m3")
        _embedding_model = BGEM3FlagModel(
            model_path,
            use_fp16=True,
            device='cpu',
            local_files_only=os.getenv("HF_LOCAL_FILES_ONLY", "0") == "1"
        )
        _model_name = "bge-m3"
        logger.info("Loaded BGE-M3 embedding model")
        return _embedding_model
    except Exception as e:
        logger.warning(f"BGE-M3 load failed: {e}")

    # 2. 备选：sentence-transformers 的 MiniLM（自动下载，约 80MB）
    try:
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("FALLBACK_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        _embedding_model = SentenceTransformer(model_name)
        _model_name = model_name
        logger.info(f"Loaded fallback embedding model: {model_name}")
        return _embedding_model
    except Exception as e:
        logger.error(f"All embedding models failed: {e}")
        _embedding_model = None
        return None

def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    model = get_embedding_model()
    if model is None:
        return None
    try:
        if _model_name == "bge-m3":
            return model.encode(texts)['dense_vecs'].tolist()
        else:
            return model.encode(texts).tolist()
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return None