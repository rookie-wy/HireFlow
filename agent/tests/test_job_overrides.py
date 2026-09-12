"""岗位级配置（O7）测试：权重解析与检索参数覆盖。

关键语义：
  - 岗位覆盖 > 类别默认；
  - 只写想调的专家时，其余专家权重置 0（而不是悄悄掺入默认值）；
  - 非法输入（未知专家/非正数/非数字）整体回退默认并告警，不产生"半配置"隐式行为。
"""
from __future__ import annotations

from app.agents.registry import WEIGHTS_BY_CATEGORY, resolve_weights
from app.services.screening.hybrid_screener import HybridScreener
from app.services.screening.reranker import apply_overrides, effective_mode, reset_overrides


def _screener(job_overrides: dict | None = None) -> HybridScreener:
    job = {
        "job_id": "j1",
        "title": "测试岗位",
        "jd_json": {"job_category": "tech"},
    }
    if job_overrides is not None:
        job["screen_overrides"] = job_overrides
    return HybridScreener("t1", job, [{"candidate_id": "c1", "resume_text": "x", "structured_json": {}}])


# ---------- 权重解析 ----------
def test_default_weights_when_no_override():
    assert resolve_weights("tech") == WEIGHTS_BY_CATEGORY["tech"]


def test_override_replaces_and_zeroes_others():
    out = resolve_weights("tech", {"skill_evaluator": 0.6, "interviewer": 0.4})
    assert out["skill_evaluator"] == 0.6 and out["interviewer"] == 0.4
    assert out["culture_fit"] == 0 and out["stability_analyzer"] == 0
    assert abs(sum(out.values()) - 1.0) < 1e-6


def test_override_normalizes_when_sum_not_one():
    out = resolve_weights("tech", {"skill_evaluator": 3, "interviewer": 1})
    assert abs(sum(out.values()) - 1.0) < 1e-6
    assert abs(out["skill_evaluator"] - 0.75) < 1e-6


def test_unknown_agent_falls_back_to_default():
    assert resolve_weights("tech", {"nonexistent_agent": 0.5}) == WEIGHTS_BY_CATEGORY["tech"]


def test_non_positive_or_bad_value_falls_back():
    assert resolve_weights("tech", {"interviewer": 0}) == WEIGHTS_BY_CATEGORY["tech"]
    assert resolve_weights("tech", {"interviewer": -0.5}) == WEIGHTS_BY_CATEGORY["tech"]
    assert resolve_weights("tech", {"interviewer": "abc"}) == WEIGHTS_BY_CATEGORY["tech"]


def test_unknown_category_uses_general():
    assert resolve_weights("not_a_category") == WEIGHTS_BY_CATEGORY["general"]


# ---------- 检索参数覆盖 ----------
def test_screen_overrides_applied_and_whitelisted():
    sc = _screener({"rag_top_k": 7, "rerank_doc_chars": 123, "evil_param": 1})
    assert sc._cfg("rag_top_k") == 7
    assert sc._cfg("rerank_doc_chars") == 123
    assert "evil_param" not in sc.overrides, "白名单外的参数必须被忽略"
    assert sc._cfg("rerank_pairs_factor") == sc.settings.rerank_pairs_factor  # 未覆盖的走默认


def test_screen_overrides_type_coercion_and_bad_value():
    sc = _screener({"rag_top_k": "9", "rerank_threshold_cosine": "0.7", "rerank_doc_chars": "abc"})
    assert sc._cfg("rag_top_k") == 9          # 字符串数字可转换
    assert sc._cfg("rerank_threshold_cosine") == 0.7
    assert sc._cfg("rerank_doc_chars") == sc.settings.rerank_doc_chars  # 非法值忽略


def test_threshold_follows_mode_with_override():
    """按最终生效模式取阈值：岗位覆盖 cross_encoder → 用 cross 阈值；否则用 cosine 阈值。"""
    sc = _screener({"rerank_mode": "cross_encoder", "rerank_threshold": 0.33})
    assert abs(sc._effective_threshold() - 0.33) < 1e-9
    sc2 = _screener({"rerank_threshold_cosine": 0.66})
    assert abs(sc2._effective_threshold() - 0.66) < 1e-9


def test_threshold_uses_session_mode_when_no_job_override():
    """岗位未覆盖模式时，会话级覆盖应生效（与 reranker.effective_mode 保持一致）。"""
    token = apply_overrides({"rerank_mode": "cross_encoder"})
    try:
        sc = _screener()
        assert abs(sc._effective_threshold() - sc.settings.rerank_threshold) < 1e-9
    finally:
        reset_overrides(token)


def test_reranker_session_override_isolated():
    """contextvars 覆盖：设置后生效、reset 后恢复，避免并发任务串味。"""
    base = effective_mode()
    token = apply_overrides({"rerank_mode": "cross_encoder"})
    try:
        assert effective_mode() == "cross_encoder"
    finally:
        reset_overrides(token)
    assert effective_mode() == base
