"""Agent 注册表：按岗位类别组合专家组与仲裁权重。"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.agents.base import BaseAgent
from app.core.errors import get_logger
from app.agents.experts import (
    CultureFitAgent,
    InterviewerAgent,
    LeadershipAgent,
    SkillEvaluationAgent,
    StabilityAnalyzer,
    VisualEvaluationAgent,
)

# 专家组：按类别实例化
log = get_logger(__name__)

_AGENT_PROTOTYPES: Dict[str, List[BaseAgent]] = {
    "interviewer": InterviewerAgent(),
    "skill_evaluator": SkillEvaluationAgent(),
    "culture_fit": CultureFitAgent(),
    "leadership": LeadershipAgent(),
    "visual_evaluator": VisualEvaluationAgent(),
    "stability_analyzer": StabilityAnalyzer(),
}

# 仲裁权重表（v5 §4.3 Stage 4，各和为 1）
WEIGHTS_BY_CATEGORY: Dict[str, Dict[str, float]] = {
    "tech": {"interviewer": 0.35, "skill_evaluator": 0.35, "culture_fit": 0.15, "stability_analyzer": 0.15},
    "management": {"interviewer": 0.35, "leadership": 0.35, "culture_fit": 0.15, "stability_analyzer": 0.15},
    "design": {"interviewer": 0.30, "skill_evaluator": 0.25, "visual_evaluator": 0.15, "culture_fit": 0.15, "stability_analyzer": 0.15},
    "general": {"interviewer": 0.50, "culture_fit": 0.30, "stability_analyzer": 0.20},
}


def get_agents_by_category(category: str) -> List[BaseAgent]:
    """返回该岗位类别的专家组；非法类别回退 general。"""
    key = category if category in WEIGHTS_BY_CATEGORY else "general"
    order = list(WEIGHTS_BY_CATEGORY[key].keys())
    return [_AGENT_PROTOTYPES[name] for name in order if name in _AGENT_PROTOTYPES]


def get_weights(category: str) -> Dict[str, float]:
    return WEIGHTS_BY_CATEGORY.get(category, WEIGHTS_BY_CATEGORY["general"])


def resolve_weights(category: str, override: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """解析最终仲裁权重：岗位级覆盖 > 类别默认（O7）。

    校验（任一条不满足就整体回退默认权重并告警，避免"配错一半"产生隐式行为）：
      - 键必须是该类别专家组内的专家；
      - 值必须为正；
      - 归一化后使用（容忍 0.99~1.01 的浮点误差，超出范围也归一化，但记录告警）。
    """
    base = dict(get_weights(category))
    if not override:
        return base
    unknown = [k for k in override if k not in base]
    if unknown:
        log.warning("weights override ignored: unknown agents %s (category=%s)", unknown, category)
        return base
    try:
        values = {k: float(v) for k, v in override.items()}
    except (TypeError, ValueError):
        log.warning("weights override ignored: non-numeric value (category=%s)", category)
        return base
    if any(v <= 0 for v in values.values()):
        log.warning("weights override ignored: non-positive weight (category=%s)", category)
        return base
    # 未在覆盖中出现的专家：权重置 0（等价于不参与仲裁），而不是回退默认值——
    # 否则"我只想把技能权重调到 0.6"会被悄悄掺入其他默认权重，结果不符合预期。
    merged = {agent: float(values.get(agent, 0.0)) for agent in base}
    total = sum(merged.values())
    if total <= 0:
        log.warning("weights override ignored: sum<=0 (category=%s)", category)
        return base
    if abs(total - 1.0) > 0.01:
        log.warning("weights override sum=%.3f, normalized (category=%s)", total, category)
    return {agent: round(w / total, 6) for agent, w in merged.items()}
