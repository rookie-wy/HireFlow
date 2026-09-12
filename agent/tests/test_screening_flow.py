"""圆桌讨论模块测试：mock LLM 验证全流程。"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.agents.schemas import AgentEvaluationResult
from app.agents.moderator import ModeratorAgent
from app.agents.registry import get_weights
from app.services.screening.hard_filter import hard_filter
from app.services.screening.bm25_index import BM25Index


# ---------- 硬过滤 ----------
def test_hard_filter_degree_and_years():
    reqs = ["硕士及以上学历", "3年以上经验"]
    skill_graph = ["Python", "Go"]
    candidates = [
        {"candidate_id": "c1", "resume_text": "python go",
         "structured_json": {"education": [{"degree": "硕士"}], "work_experience": [
             {"start_date": "2020-01", "end_date": "2024-01"}], "skills": ["Python"]}},
        {"candidate_id": "c2", "resume_text": "java",
         "structured_json": {"education": [{"degree": "本科"}], "work_experience": [
             {"start_date": "2020-01", "end_date": "2024-01"}], "skills": ["Java"]}},
        {"candidate_id": "c3", "resume_text": "python",
         "structured_json": {"education": [{"degree": "硕士"}], "work_experience": [], "skills": ["Python"]}},
    ]
    passed = hard_filter(reqs, skill_graph, candidates)
    ids = {c["candidate_id"] for c in passed}
    assert ids == {"c1"}  # c2 学历不够；c3 年限不足


# ---------- BM25 ----------
def test_bm25_ranking():
    idx = BM25Index(["Python 机器学习 深度学习", "Java Spring 微服务", "Python Go 后端"])
    hits = idx.search("Python", 3)
    assert hits and hits[0][0] in (0, 2)


# ---------- 仲裁公式 ----------
def test_arbitrate_confidence_weighted():
    m = ModeratorAgent()
    results = [
        AgentEvaluationResult(agent="interviewer", score=80, confidence=0.9),
        AgentEvaluationResult(agent="skill_evaluator", score=60, confidence=0.8),
        AgentEvaluationResult(agent="culture_fit", score=70, confidence=0.7),
        AgentEvaluationResult(agent="stability_analyzer", score=90, confidence=0.9),
    ]
    overall, _ = m.arbitrate(results, "tech", get_weights("tech"))
    # num = .35*.9*80+.35*.8*60+.15*.7*70+.15*.9*90 = 61.5; den = .835 → 73.65
    assert abs(overall - 73.7) < 0.15


def test_arbitrate_ignores_devil_advocate():
    m = ModeratorAgent()
    results = [
        AgentEvaluationResult(agent="interviewer", score=80, confidence=0.9),
        AgentEvaluationResult(agent="culture_fit", score=80, confidence=0.9),
        AgentEvaluationResult(agent="stability_analyzer", score=80, confidence=0.9),
        AgentEvaluationResult(agent="devils_advocate", score=10, confidence=0.9),
    ]
    overall, _ = m.arbitrate(results, "general", get_weights("general"))
    assert overall == 80.0  # 魔鬼代言人不参与加权


# ---------- 分歧检测 ----------
def test_detect_divergence_threshold():
    m = ModeratorAgent()
    low = [
        AgentEvaluationResult(agent="interviewer", score=75, confidence=0.8),
        AgentEvaluationResult(agent="skill_evaluator", score=72, confidence=0.8),
    ]
    _mean, _std, needs = m.detect_divergence(low)
    assert not needs  # std 2.1 < 12

    high = [
        AgentEvaluationResult(agent="interviewer", score=95, confidence=0.8),
        AgentEvaluationResult(agent="skill_evaluator", score=40, confidence=0.8),
    ]
    _mean, _std, needs2 = m.detect_divergence(high)
    assert needs2


# ---------- NDJSON 全流程（mock LLM） ----------
@pytest.fixture
def mock_llm(monkeypatch):
    """按 prompt 关键词返回不同模拟结果；记录调用。"""
    calls = []

    from app.infra.llm_client import LLMClient

    # chat_json 是同步方法（内部走 SDK 同步调用）：直接 patch 类方法。
    # 注意别用 async def —— 那会被当作协程函数，调用后从未 await（RuntimeWarning + 假数据）。
    def fake_chat_json(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        calls.append(prompt[:50])
        if "资深技术面试官" in prompt or "评估要求" in prompt:
            agent = _guess_agent(prompt)
            score = _SCORES.get(agent, 70)
            return {
                "score": score,
                "dimension_scores": {"d1": score},
                "evidence": [f"{agent} 证据：熟悉相关技术栈"],
                "confidence": 0.8,
            }, None
        if "圆桌评审中的" in prompt:
            import random

            return {"stance": "revise", "score": _SCORES[_extract_agent(prompt)],
                    "dimension_scores": {}, "evidence": [], "reasoning": "参考同伴证据后微调"}, None
        if "魔鬼代言人" in prompt:
            return {"argument": "技能列表宽泛但核心栈深度存疑", "evidence": []}, None
        if "推荐语" in prompt:
            return {"recommendation": "技能匹配良好，建议进入面试。"}, None
        return {"resume": "理想候选人：精通Python与机器学习，五年经验"}, None

    from app.infra.llm_client import LLMClient

    monkeypatch.setattr(LLMClient, "chat_json", fake_chat_json)
    return calls


_SCORES = {"interviewer": 90, "skill_evaluator": 45, "culture_fit": 85, "stability_analyzer": 88}


def _guess_agent(prompt: str) -> str:
    for name in ("interviewer", "skill_evaluator", "culture_fit", "leadership", "visual_evaluator"):
        if name.split("_")[0] in prompt or {"interviewer": "面试官", "skill_evaluator": "技能评估",
                                            "culture_fit": "文化"}.get(name, "") in prompt:
            if _signature(name) in prompt:
                return name
    if "面试官" in prompt:
        return "interviewer"
    if "技能" in prompt:
        return "skill_evaluator"
    if "文化" in prompt:
        return "culture_fit"
    return "interviewer"


def _signature(name: str) -> str:
    return {
        "interviewer": "资深技术面试官",
        "skill_evaluator": "技能评估专家",
        "culture_fit": "团队文化评估专家",
        "leadership": "领导力评估专家",
        "visual_evaluator": "设计作品评估专家",
    }.get(name, name)


def _extract_agent(prompt: str) -> str:
    m = [a for a in ("interviewer", "skill_evaluator", "culture_fit") if f"圆桌评审中的{a}" in prompt]
    return m[0] if m else "interviewer"


def test_full_screening_flow(mock_llm):
    """mock LLM 下跑通 粗筛→圆桌→仲裁 全流程，校验事件序列与真实 ID。"""
    from app.services.screening.orchestrator import run_screening

    payload = {
        "tenant_id": "t1",
        "job": {
            "job_id": "j1", "title": "Python 工程师",
            "jd_json": {
                "title": "Python 工程师",
                "hard_requirements": ["本科及以上学历"],
                "soft_requirements": ["沟通"],
                "skill_graph": ["Python", "Machine Learning"],
                "job_category": "tech",
            },
        },
        "candidates": [
            {"candidate_id": "c1", "resume_text": "Python 机器学习 五年经验",
             "structured_json": {"education": [{"degree": "本科"}], "skills": ["Python"],
                                 "work_experience": [{"start_date": "2021-01", "end_date": "2026-01"}]}},
            {"candidate_id": "c2", "resume_text": "Java 开发",
             "structured_json": {"education": [{"degree": "本科"}], "skills": ["Java"],
                                 "work_experience": [{"start_date": "2021-01", "end_date": "2026-01"}]}},
        ],
        "config": {"max_candidates": 5, "query": "Python 机器学习", "enable_hyde": False},
    }

    async def collect():
        events = []
        async for line in run_screening(payload):
            events.append(json.loads(line))
        return events

    events = asyncio.run(collect())
    types = [e["type"] for e in events]

    assert types[0] == "stage"
    assert "rough_result" in types
    assert types[-1] == "done"
    assert "error" not in types

    rough = next(e for e in events if e["type"] == "rough_result")
    # c2 是 Java 候选人：技能/文本都不命中 Python，但硬过滤只卡学历，RRF 空时回退池顺序 → 可能入选。
    # 关键断言：所有 candidate_id 都是真实 ID（无 unknown/bm25_ 占位）
    for c in rough["candidates"]:
        assert c["candidate_id"] in {"c1", "c2"}

    if "candidate_done" in types:
        done = next(e for e in events if e["type"] == "done")
        for r in done["results"]:
            assert r["candidate_id"] in {"c1", "c2"}
            assert 0 <= r["overall_score"] <= 100
            assert r["agent_details"]


# ---------- O4：分批粗筛（打破 200 人上限） ----------
def test_batched_screening_covers_all_candidates(mock_llm):
    """多批候选：全量参与粗筛、结果不重复、pool_size 反映真实总数。"""
    from app.services.screening.orchestrator import run_screening

    def mk(cid: str, skill: str) -> dict:
        return {
            "candidate_id": cid,
            "resume_text": f"{skill} 开发 五年经验",
            "structured_json": {
                "education": [{"degree": "本科"}],
                "skills": [skill],
                "work_experience": [{"start_date": "2021-01", "end_date": "2026-01"}],
            },
        }

    batch1 = [mk(f"a{i}", "Python") for i in range(4)]
    batch2 = [mk(f"b{i}", "Python") for i in range(3)]
    payload = {
        "tenant_id": "t1",
        "job": {
            "job_id": "j1", "title": "Python 工程师",
            "jd_json": {"title": "Python 工程师", "hard_requirements": ["本科及以上学历"],
                        "soft_requirements": [], "skill_graph": ["Python"], "job_category": "tech"},
        },
        "batches": [batch1, batch2],          # 分两批传入（等价于 backend 分页加载）
        "config": {"max_candidates": 10, "query": "Python", "enable_hyde": False},
    }

    async def collect():
        events = []
        async for line in run_screening(payload):
            events.append(json.loads(line))
        return events

    events = asyncio.run(collect())
    types = [e["type"] for e in events]
    assert types[-1] == "done" and "error" not in types

    stages = [e for e in events if e["type"] == "stage" and "粗筛进度" in str(e.get("message"))]
    assert len(stages) == 2, f"应有两批进度事件，实际 {len(stages)}"

    rough = next(e for e in events if e["type"] == "rough_result")
    assert rough["pool_size"] == 7, f"pool_size 应为全部候选人数 7，实际 {rough['pool_size']}"
    assert rough.get("batches") == 2

    ids = [c["candidate_id"] for c in rough["candidates"]]
    assert len(ids) == len(set(ids)), "合并后不应出现重复 candidate_id"
    assert set(ids).issubset({c["candidate_id"] for c in batch1 + batch2})
    print(f"分批粗筛: 入池 {len(ids)} 人 / 共 7 人，批次数 {rough.get('batches')}")
