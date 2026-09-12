"""筛选编排：粗筛 → 精筛 → NDJSON 事件流。

事件类型：
  stage / rough_result / fine_start / agent_result / divergence /
  discussion / candidate_done / candidate_failed / cost / done / error

大批量（O4）：backend 可分页传入 `batches`（每页一批候选人），本模块对**全量批次**做硬过滤 + 双路召回，
合并去重后统一重排，彻底去掉「只取最近 200 人」的静默截断。
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Dict, List

from app.agents.engine import FineScreeningEngine
from app.core.errors import AgentError, get_logger
from app.services.screening.hybrid_screener import HybridScreener

log = get_logger(__name__)


def _dump(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, default=_default) + "\n"


def _default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def _usage_dict(u) -> dict:
    return {
        "model_name": u.model,
        "tokens_prompt": u.tokens_prompt,
        "tokens_completion": u.tokens_completion,
        "cost": round(u.cost, 6),
    }


def _collect_batches(payload: dict) -> List[List[dict]]:
    """把请求载荷归一成批次列表：兼容单批 candidates 与多批 batches 两种写法。"""
    batches = payload.get("batches")
    if batches:
        out = [list(b) for b in batches if b]
        if out:
            return out
    single = payload.get("candidates") or []
    return [list(single)] if single else []


async def run_screening(payload: dict) -> AsyncIterator[str]:
    """执行完整筛选并以 NDJSON 行流式返回（外包一层任务级指标）。

    指标（O6）：
      screen_tasks_total{status=completed|failed}  任务成败计数
      screen_task_seconds                          任务总耗时直方图
      screen_results_total{cached}                 产出结果数（区分是否复用缓存）
      screen_discussion_rounds                     触发圆桌讨论的候选人轮次分布
    """
    import time as _t

    from app.core.metrics import inc, observe

    started = _t.perf_counter()
    status = "failed"
    results_total = 0
    cached_total = 0
    try:
        async for line in _run_screening_inner(payload):
            # 解析事件类型做统计（JSON 字段顺序不保证，不能靠字符串前缀判断）
            try:
                ev = json.loads(line)
            except Exception:  # noqa: BLE001
                yield line
                continue
            ev_type = ev.get("type")
            if ev_type == "done":
                status = "completed"
                results_total += len(ev.get("results") or [])
            elif ev_type == "candidate_done" and ev.get("cached"):
                cached_total += 1
            yield line
    finally:
        inc("screen_tasks_total", status=status)
        observe("screen_task_seconds", _t.perf_counter() - started, status=status)
        if results_total:
            inc("screen_results_total", results_total, cached="false")
        if cached_total:
            inc("screen_results_total", cached_total, cached="true")
        log.info("screen task finished status=%s results=%d cached=%d elapsed=%.2fs",
                 status, results_total, cached_total, _t.perf_counter() - started)


async def _run_screening_inner(payload: dict) -> AsyncIterator[str]:
    """执行完整筛选并以 NDJSON 行流式返回。"""
    tenant_id = str(payload.get("tenant_id") or "")
    job = payload.get("job") or {}
    batches = _collect_batches(payload)
    candidates: List[dict] = [c for b in batches for c in b]
    config = payload.get("config") or {}
    max_candidates = int(config.get("max_candidates") or 10)
    query = str(config.get("query") or "")
    enable_hyde = bool(config.get("enable_hyde", True))
    cached_reports = payload.get("cached_reports") or {}
    usages: List[dict] = []

    try:
        if not tenant_id or not job:
            raise AgentError("tenant_id 与 job 必填")
        if not candidates:
            yield _dump({"type": "done", "results": [], "message": "无候选候选人"})
            return

        total = len(candidates)
        yield _dump({
            "type": "stage", "stage": "rough", "progress": 5,
            "message": f"开始混合粗筛（{total} 人 / {len(batches)} 批）",
        })

        # 岗位级参数覆盖（O7）：整段筛选会话内生效（contextvars，线程内可见）
        from app.services.screening.reranker import apply_overrides, reset_overrides

        overrides_token = apply_overrides(job.get("screen_overrides") or {})

        first = HybridScreener(tenant_id, job, batches[0])
        if not query:
            query = first._default_query()

        # HyDE 改写（1 次 LLM）+ 查询向量（1 次嵌入）跨批次共享，避免每批重复计算
        hyde_text = query
        if enable_hyde:
            rewritten, u = first._hyde_rewrite(query)
            if u is not None:
                usages.append(_usage_dict(u))
                yield _dump({"type": "cost", "usage": _usage_dict(u)})
            hyde_text = rewritten

        query_vec = None
        try:
            from app.infra.embedding_client import embed_texts

            vecs = embed_texts([hyde_text])
            query_vec = vecs[0] if vecs else None
        except Exception as exc:  # noqa: BLE001 稠密检索不可用时降级为 BM25
            log.warning("query embedding failed, dense retrieval disabled: %s", exc)

        # ---- 分批粗筛：硬过滤 + 双路召回逐批进行，合并去重 ----
        merged: Dict[str, dict] = {}
        evidence_map: Dict[str, List[str]] = {}
        for bi, batch in enumerate(batches):
            screener = first if bi == 0 else HybridScreener(tenant_id, job, batch)
            results, batch_evidence = await asyncio.to_thread(
                screener.screen_batch, query, query_vec, hyde_text
            )
            for r in results:
                cid = r["candidate_id"]
                prev = merged.get(cid)
                if prev is None or r["score"] > prev["score"]:
                    merged[cid] = r
            for cid, ev in batch_evidence.items():
                evidence_map.setdefault(cid, []).extend(ev)
            yield _dump({
                "type": "stage", "stage": "rough",
                "progress": 5 + int(25 * (bi + 1) / len(batches)),
                "message": f"粗筛进度 {bi + 1}/{len(batches)} 批，累计入池 {len(merged)} 人",
            })

        # ---- 统一重排（只做一次，控制成本）----
        by_id = {c["candidate_id"]: c for c in candidates}
        ranked = await asyncio.to_thread(
            first.finalize_ranking, query, merged, by_id, evidence_map, max_candidates
        )
        for r in ranked:
            r["reasons"] = first._reasons(r)

        cache_hits = sum(1 for r in ranked if r["candidate_id"] in cached_reports)
        if cache_hits:
            from app.core.metrics import inc

            inc("screen_cache_hit_candidates_total", cache_hits)
        yield _dump({
            "type": "rough_result", "candidates": ranked,
            "pool_size": total, "progress": 35, "cache_hits": cache_hits,
            "batches": len(batches),
        })

        if not ranked:
            yield _dump({"type": "done", "results": [], "message": "粗筛无通过候选人"})
            return

        fine_pool = [by_id[r["candidate_id"]] for r in ranked if r["candidate_id"] in by_id]

        engine = FineScreeningEngine()
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        task = asyncio.get_running_loop().create_task(
            engine.screen_candidates(job, fine_pool, on_event, cached_reports=cached_reports)
        )

        # 事件泵：队列非空即吐出；任务结束后排空残余
        while not task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.05 if task.done() else 1.0)
                if event.get("type") == "discussion":
                    round_no = (event.get("turn") or {}).get("round")
                    if round_no:
                        from app.core.metrics import observe as _observe

                        _observe("screen_discussion_rounds", float(round_no))
                yield _dump(event)
            except asyncio.TimeoutError:
                continue

        reports, fine_usage = await task
        usages.extend(_usage_dict(u) for u in fine_usage)
        for u in fine_usage:
            yield _dump({"type": "cost", "usage": _usage_dict(u)})

        yield _dump({
            "type": "done", "progress": 100,
            "results": [r.model_dump() for r in reports],
        })
        reset_overrides(overrides_token)

    except AgentError as exc:
        yield _dump({"type": "error", "code": exc.code, "message": exc.message})
    except Exception as exc:  # noqa: BLE001
        log.exception("screening run failed")
        yield _dump({"type": "error", "code": 50000, "message": str(exc)[:200]})
