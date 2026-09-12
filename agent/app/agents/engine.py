"""精筛引擎：独立评估 → 分歧检测 → 圆桌讨论 → 仲裁 → 可解释报告。

on_event 回调逐事件产出（供 /screening/run NDJSON 流式输出）。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, List, Optional

from app.agents.moderator import ModeratorAgent
from app.agents.registry import get_agents_by_category, get_weights, resolve_weights
from app.agents.schemas import AgentEvaluationResult, OverallReport
from app.core.config import get_settings
from app.core.errors import get_logger
from app.core.metrics import inc, timer
from app.infra.llm_client import LLMResponse, get_llm_client

log = get_logger(__name__)

EventType = str
OnEvent = Callable[[dict], Awaitable[None]]

# 专家评估并发上限（跨事件循环安全的懒初始化单例）
_llm_sem: Optional[asyncio.Semaphore] = None


def _llm_semaphore() -> asyncio.Semaphore:
    """限制同时在飞的 LLM 请求数（默认 4，可用 LLM_MAX_CONCURRENCY 调整）。

    注意：asyncio.Semaphore 绑定事件循环，uvicorn 单 worker 下是安全的；
    多 worker 时每个进程各自持有一把，总并发 = worker 数 × 该值。
    """
    global _llm_sem
    if _llm_sem is None:
        _llm_sem = asyncio.Semaphore(max(1, get_settings().llm_max_concurrency))
    return _llm_sem


class FineScreeningEngine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.moderator = ModeratorAgent()

    async def screen_candidates(
        self,
        job: dict,
        candidates: List[dict],
        on_event: Optional[OnEvent] = None,
        cached_reports: Optional[Dict[str, dict]] = None,
    ) -> tuple[List[OverallReport], List[LLMResponse]]:
        """对粗筛后的候选逐个精筛。

        job: {job_id, title, jd_json}
        candidates: [{candidate_id, resume_text, structured_json}]
        cached_reports: {candidate_id: 既有精筛结论}——由 backend 依据简历指纹判定可复用，
            命中者直接复用、**不调用任何 LLM**（幂等缓存），但仍产出报告，保证落库不漏人。
        """
        usages: List[LLMResponse] = []
        cached_reports = cached_reports or {}

        reports: List[OverallReport] = []
        category = str((job.get("jd_json") or {}).get("job_category") or "general")
        agents = get_agents_by_category(category)
        # 岗位级权重覆盖（O7）：优先级 岗位覆盖 > 类别默认
        weights = resolve_weights(category, job.get("weights_override") or None)
        if job.get("weights_override"):
            log.info("using job-level weights override: %s", weights)

        for idx, cand in enumerate(candidates):
            cid = cand["candidate_id"]
            progress = 40 + int(50 * idx / max(len(candidates), 1))
            if cid in cached_reports:
                # 幂等命中：复用历史结论（指纹一致说明简历未变、岗位未变）
                report = _report_from_cache(cid, cached_reports[cid])
                reports.append(report)
                inc("screen_cache_hit_total")
                if on_event:
                    await on_event({
                        "type": "fine_start", "candidate_id": cid,
                        "agents": [a.name for a in agents], "progress": progress,
                        "cached": True,
                    })
                    await on_event({
                        "type": "candidate_done", "candidate_id": cid,
                        "report": report.model_dump(), "cached": True,
                        "message": "命中幂等缓存，复用历史精筛结论",
                    })
                log.info("fine screening cache hit for %s (overall=%.1f)", cid, report.overall_score)
                continue

            if on_event:
                await on_event({
                    "type": "fine_start", "candidate_id": cid,
                    "agents": [a.name for a in agents], "progress": progress,
                })
            try:
                report, session_usage = await self._screen_one(job, cand, agents, weights, on_event)
                reports.append(report)
                usages.extend(session_usage)
            except Exception as exc:  # noqa: BLE001 单候选失败不影响整体
                log.exception("fine screening failed for %s", cid)
                if on_event:
                    await on_event({
                        "type": "candidate_failed", "candidate_id": cid,
                        "message": str(exc)[:200],
                    })

        if on_event:
            await on_event({"type": "fine_done", "progress": 90})
        return reports, usages

    async def _screen_one(
        self, job: dict, cand: dict, agents, weights, on_event: Optional[OnEvent],
    ) -> tuple[OverallReport, List[LLMResponse]]:
        session_usage: List[LLMResponse] = []

        # Stage 1: 独立评估（LLM 专家并行；规则型稳定性内联）
        llm_agents = [a for a in agents if a.name != "stability_analyzer"]
        stability_agent = next((a for a in agents if a.name == "stability_analyzer"), None)

        async def run_agent(agent):
            """专家评估：LLM 调用是同步阻塞的，必须丢线程池才能真正并发。

            此前直接 await agent.evaluate(...)，而 evaluate 内部是同步 chat_json，
            于是 asyncio.gather 实际按顺序执行 —— 4 个专家就是 4 倍串行等待。
            用信号量限制并发，避免一次性打满上游限流。
            """
            async with _llm_semaphore():
                with timer("screen_stage_seconds", stage="agent_eval"):
                    result, usage = await asyncio.to_thread(agent.evaluate_sync, job, cand)
            if usage is not None:
                session_usage.append(usage)
            return result

        eval_results = await asyncio.gather(*(run_agent(a) for a in llm_agents))
        if stability_agent is not None:
            # 规则型分析（零 LLM 成本），直接同步执行即可
            s_result, _ = await stability_agent.evaluate(job, cand)
            eval_results.append(s_result)

        for r in eval_results:
            if on_event:
                await on_event({
                    "type": "agent_result", "candidate_id": cand["candidate_id"],
                    "result": r.model_dump(),
                })

        # Stage 2: 分歧检测
        mean, std, needs_discussion = self.moderator.detect_divergence(eval_results)
        if on_event:
            await on_event({
                "type": "divergence", "candidate_id": cand["candidate_id"],
                "mean": round(mean, 1), "std": round(std, 1),
                "needs_discussion": needs_discussion,
            })

        # Stage 3 + 4: 圆桌讨论（含魔鬼代言人）→ 仲裁
        final_results = eval_results
        transcript = None
        if needs_discussion:
            final_results, transcript, discuss_usage = await self.moderator.run_discussion(
                eval_results, job, cand, mean, std,
            )
            session_usage.extend(u for u in discuss_usage if u is not None)
            if on_event and transcript:
                for turn in transcript.turns:
                    await on_event({
                        "type": "discussion", "candidate_id": cand["candidate_id"],
                        "turn": turn.model_dump(),
                    })

        overall, dimension_scores = self.moderator.arbitrate(final_results, str(
            (job.get("jd_json") or {}).get("job_category") or "general"), weights)

        evidence = _merge_evidence(final_results)
        recommendation, rec_usage = await self.moderator.generate_recommendation(
            job, overall, final_results, evidence,
        )
        if rec_usage is not None:
            session_usage.append(rec_usage)

        report = OverallReport(
            candidate_id=cand["candidate_id"],
            overall_score=overall,
            dimension_scores=dimension_scores,
            recommendation_text=recommendation,
            evidence=evidence,
            agent_details=final_results,
            discussion=transcript,
        )
        if on_event:
            await on_event({
                "type": "candidate_done", "candidate_id": cand["candidate_id"],
                "report": report.model_dump(),
            })
        return report, session_usage


def _merge_evidence(results: List[AgentEvaluationResult], limit: int = 5) -> List[str]:
    """按置信度排序合并去重证据。"""
    pool = []
    seen = set()
    for r in results:
        for e in r.evidence:
            if e and e not in seen:
                seen.add(e)
                pool.append((r.confidence, e))
    pool.sort(key=lambda p: p[0], reverse=True)
    return [e for _c, e in pool[:limit]]

def _report_from_cache(candidate_id: str, cached: dict) -> OverallReport:
    """把 backend 传来的历史结论还原成 OverallReport（保持与实时精筛同一契约）。"""
    agent_details = []
    for a in (cached.get("agent_details") or []):
        try:
            agent_details.append(AgentEvaluationResult(**a))
        except Exception:  # noqa: BLE001 历史结构可能缺字段，跳过单条而不是整体失败
            continue
    discussion = cached.get("discussion") or cached.get("discussion_json") or None
    return OverallReport(
        candidate_id=candidate_id,
        overall_score=float(cached.get("overall_score") or 0.0),
        dimension_scores={k: float(v) for k, v in (cached.get("dimension_scores") or {}).items()},
        recommendation_text=str(cached.get("recommendation_text") or ""),
        evidence=[str(e) for e in (cached.get("evidence") or [])],
        agent_details=agent_details,
        discussion=discussion,
    )
