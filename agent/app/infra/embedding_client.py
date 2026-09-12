"""嵌入与重排客户端（BGE-M3 / BGE-Reranker，懒加载单例，带降级）。"""
from __future__ import annotations

import threading
from typing import List, Optional

from app.core.config import get_settings
from app.core.errors import get_logger

log = get_logger(__name__)

_embedder = None
_embedder_lock = threading.Lock()
_embedder_backend = ""
_reranker = None
_reranker_lock = threading.Lock()
_reranker_failed = False

# 推理锁（两模型**共用一把**，实测必须如此）：
#   1) 正确性：FlagEmbedding 的 encode/compute_score 共享 tokenizer 与内部缓冲，
#      并发调用会抛 `AttributeError: 'list' object has no attribute 'keys'`（tokenizer.pad 收到 list）；
#   2) 性能：两个模型各跑 torch 多线程会严重超订 CPU（本机 14 线程 × 2 模型），
#      实测「嵌入与重排各持一把锁并行」时，重排单次从 2s 恶化到 48s（饿死）。
# 目标机要么单 GPU 要么 CPU：前后向串行本来就是常态，共用锁既正确又不损失吞吐。
_model_infer_lock = threading.Lock()




def _is_known_race(exc: BaseException) -> bool:
    """FlagEmbedding 并发下 tokenizer.pad 收到 list 的已知竞态特征。"""
    text = f"{type(exc).__name__}: {exc}"
    return "has no attribute 'keys'" in text or "pad_with_compat" in text


def _configure_torch_threads() -> None:
    """限制 torch 线程数，避免多模型各自开满线程导致 CPU 超订。

    实测：本机默认 14 线程，2 个模型共存时重排单次从 ~2s 恶化到 21s（CPU 超订 + 内存带宽争抢）。
    注意必须在**模型加载之后**再设一次——试验发现 FlagEmbedding 加载权重会把线程数重置回默认值。
    幂等且开销可忽略，所以在每次模型加载完成后都调用。
    """
    try:
        import torch

        n = max(1, get_settings().torch_num_threads)
        if torch.get_num_threads() != n:
            torch.set_num_threads(n)
            log.info("torch threads set to %d", n)
    except Exception:  # noqa: BLE001 torch 不可用时无需配置
        pass


def _load_embedder():
    global _embedder, _embedder_backend
    _configure_torch_threads()
    s = get_settings()
    try:
        from FlagEmbedding import BGEM3FlagModel

        _embedder = BGEM3FlagModel(s.embedding_model_path, use_fp16=True, device=s.embedding_device)
        _embedder_backend = "bge-m3"
        _configure_torch_threads()  # 加载后重置（库会改回默认线程数）
        log.info("embedder loaded: %s", s.embedding_model_path)
        return _embedder
    except Exception as exc:  # noqa: BLE001
        log.warning("BGE-M3 load failed (%s), fallback to %s", exc, s.embedding_fallback_model)
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(s.embedding_fallback_model, device=s.embedding_device)
        _embedder_backend = "minilm"
        return _embedder


def get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = _load_embedder()
    return _embedder


def embed_backend() -> str:
    get_embedder()
    return _embedder_backend


def embedder_ready() -> bool:
    """模型是否已加载（不触发加载，供 /healthz 反映预热状态）。"""
    return _embedder is not None


def warmup() -> None:
    """预热嵌入/重排模型（后台调用，两者**并行**加载）。

    动机：模型是懒加载单例，首次请求要等 2.27GB 权重进内存（实测 bge-m3 约 29s、
    reranker 约 10s），表现为「上传第一份简历特别慢」。
    实测教训：串行 warmup 会让首个请求等两者之和（~38s），并行后只需等 embedder 加载完
    （上传路径只依赖 embedder；reranker 在精筛时才用），所以两个加载放不同线程。
    """
    import threading
    import time as _time

    from app.core.metrics import observe, set_gauge

    def _load(name: str, loader) -> None:
        start = _time.perf_counter()
        try:
            loader()
            set_gauge("agent_model_ready", 1, model=name)
        except Exception:  # noqa: BLE001 预热失败不影响服务启动
            set_gauge("agent_model_ready", 0, model=name)
            log.exception("warmup failed for %s", name)
        finally:
            observe("model_load_seconds", _time.perf_counter() - start, model=name)

    # embedder 先起（上传/粗筛的硬依赖）
    threads = [
        threading.Thread(target=_load, args=("embedder", get_embedder), name="warmup-embedder"),
    ]
    # cross-encoder 重排模型只在 RERANK_MODE=cross_encoder 时才需要：
    # cosine 模式（默认）用它不上，白占 ~2.3GB 内存与约 10s 加载时间
    if (get_settings().rerank_mode or "cosine").lower() == "cross_encoder":
        threads.append(
            threading.Thread(target=_load, args=("reranker", get_reranker), name="warmup-reranker")
        )
    else:
        set_gauge("agent_model_ready", 0, model="reranker")
        log.info("reranker warmup skipped (RERANK_MODE=%s)", get_settings().rerank_mode)
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """批量嵌入；失败返回 None（调用方降级为规则路径）。

    batch_size/max_length 显式给值：简历 chunk 长度固定（默认 500 字符），
    按 512 token 截断即可，避免默认 8192 让 CPU 推理做无谓的长序列计算。
    """
    if not texts:
        return []
    try:
        model = get_embedder()
        s = get_settings()
        with _model_infer_lock:  # 串行化推理，避免 tokenizer/缓冲竞态
            if _embedder_backend == "bge-m3":
                result = model.encode(
                    texts,
                    batch_size=s.embedding_batch_size,
                    max_length=s.embedding_max_length,
                )
                vecs = result["dense_vecs"]
            else:
                vecs = model.encode(
                    texts,
                    batch_size=s.embedding_batch_size,
                    normalize_embeddings=True,
                )
        return [v.tolist() for v in vecs]
    except Exception as exc:  # noqa: BLE001
        # 已知竞态特征（tokenizer.pad 收到 list）重试一次，其余错误直接降级
        if _is_known_race(exc):
            log.warning("embed_texts race detected, retrying once: %s", exc)
            try:
                with _model_infer_lock:
                    if _embedder_backend == "bge-m3":
                        result = model.encode(texts, batch_size=s.embedding_batch_size,
                                              max_length=s.embedding_max_length)
                        vecs = result["dense_vecs"]
                    else:
                        vecs = model.encode(texts, batch_size=s.embedding_batch_size,
                                            normalize_embeddings=True)
                return [v.tolist() for v in vecs]
            except Exception:  # noqa: BLE001
                log.exception("embed_texts retry failed")
                return None
        log.exception("embed_texts failed")
        return None


def get_reranker():
    global _reranker, _reranker_failed
    if _reranker is not None:
        return _reranker
    if _reranker_failed:
        return None
    with _reranker_lock:
        if _reranker is None and not _reranker_failed:
            try:
                from FlagEmbedding import FlagReranker

                _configure_torch_threads()
                s = get_settings()
                # CPU 上 fp16 需要模拟，实测 fp32 反而更快（2 对 1.74s vs 2.22s），按设备选择
                _reranker = FlagReranker(
                    s.reranker_model_path,
                    use_fp16=s.reranker_device != "cpu",
                    device=s.reranker_device,
                )
                _configure_torch_threads()  # 加载后重置
                log.info("reranker loaded: %s", s.reranker_model_path)
            except Exception as exc:  # noqa: BLE001
                _reranker_failed = True
                log.warning("reranker load failed (%s), rerank disabled", exc)
    return _reranker


def rerank(query: str, documents: List[str]) -> Optional[List[float]]:
    """对 [query, doc] 对打分；不可用时返回 None。"""
    model = get_reranker()
    if model is None or not documents:
        return None
    try:
        with _model_infer_lock:  # 同上：compute_score 非线程安全
            import time as _t

            started = _t.perf_counter()
            scores = model.compute_score([[query, doc] for doc in documents], normalize=True)
            log.info("rerank(cross_encoder): pairs=%d elapsed=%.2fs",
                     len(documents), _t.perf_counter() - started)
        if isinstance(scores, float):
            return [scores]
        return list(scores)
    except Exception:  # noqa: BLE001
        log.exception("rerank failed")
        return None


def rerank_query_docs(query: str, documents: List[str]) -> Optional[List[float]]:
    """别名接口，保持调用方语义清晰。"""
    return rerank(query, documents)
