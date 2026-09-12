"""精筛并发回归测试：验证 LLM 专家评估是**真并发**而不是串行。

背景：此前 `evaluate` 是 async 但内部调用同步 `chat_json`，`asyncio.gather` 因此退化为串行，
4 个专家就是 4 倍等待。现在走 `asyncio.to_thread(agent.evaluate_sync, ...)` + 信号量。
本测试用「每个专家 sleep 0.5s」的假 LLM 度量墙钟时间：
  并发 → ~0.5s；串行 → ~2.0s。断言 < 1.2s 足以区分两种实现。
"""
from __future__ import annotations

import asyncio
import time

from app.agents.engine import FineScreeningEngine
from app.agents.schemas import AgentEvaluationResult
from app.infra.llm_client import LLMClient

SLEEP_PER_AGENT = 0.5
N_AGENTS = 4

JOB = {"job_id": "j1", "title": "Python 工程师",
       "jd_json": {"job_category": "tech", "hard_requirements": [], "soft_requirements": [], "skill_graph": ["Python"]}}
CAND = {"candidate_id": "c1", "resume_text": "Python 五年", "structured_json": {"skills": ["Python"]}}


def _patch_llm(monkeypatch):
    """让 LLM 调用变成可控 sleep，并返回合法的专家评估 JSON。"""

    def fake_chat_json(self, messages, **kwargs):
        time.sleep(SLEEP_PER_AGENT)
        return {
            "score": 80,
            "dimension_scores": {"d": 80},
            "evidence": ["证据"],
            "confidence": 0.8,
        }, None

    monkeypatch.setattr(LLMClient, "chat_json", fake_chat_json)


def test_expert_evaluation_runs_concurrently(monkeypatch):
    _patch_llm(monkeypatch)
    FineScreeningEngine()  # 触发单例初始化（构造函数不做重活）

    from app.agents.registry import get_agents_by_category

    tech_agents = get_agents_by_category("tech")
    llm_agents = [a for a in tech_agents if a.name != "stability_analyzer"]

    async def run():
        started = time.perf_counter()
        results = await asyncio.gather(
            *(asyncio.to_thread(a.evaluate_sync, JOB, CAND) for a in llm_agents)
        )
        return time.perf_counter() - started, results

    elapsed, results = asyncio.run(run())
    assert len(results) == len(llm_agents)
    serial_expected = SLEEP_PER_AGENT * len(llm_agents)
    assert elapsed < serial_expected * 0.6, (
        f"专家评估疑似串行：{elapsed:.2f}s（并发应≈{SLEEP_PER_AGENT:.1f}s，串行≈{serial_expected:.1f}s）"
    )


def test_engine_screen_one_is_parallel(monkeypatch):
    """走完整 _screen_one：专家并发 + 仲裁 + 推荐语，整体墙钟应远小于串行累计。"""
    _patch_llm(monkeypatch)
    engine = FineScreeningEngine()

    async def on_event(_ev: dict) -> None:
        return None

    from app.agents.registry import get_agents_by_category, get_weights

    agents = get_agents_by_category("tech")
    weights = get_weights("tech")

    async def run():
        started = time.perf_counter()
        report, usage = await engine._screen_one(JOB, CAND, agents, weights, on_event)
        return time.perf_counter() - started, report, usage

    elapsed, report, _usage = asyncio.run(run())
    assert report.candidate_id == "c1"
    assert report.agent_details, "应包含专家明细"
    # 串行下界：4 个 LLM 专家 + 讨论/推荐语（这里评分乐观，不触发讨论）
    assert elapsed < SLEEP_PER_AGENT * 3, (
        f"_screen_one 耗时 {elapsed:.2f}s，疑似专家评估串行（串行应≥{SLEEP_PER_AGENT * 4:.1f}s）"
    )
