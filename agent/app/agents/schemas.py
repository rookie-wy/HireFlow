"""圆桌讨论模块数据契约。"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AgentEvaluationResult(BaseModel):
    """单个 Agent 的评估结果。"""

    agent: str
    score: float = Field(ge=0, le=100)
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)
    # 讨论阶段字段
    stance: Optional[Literal["maintain", "revise"]] = None
    reasoning: str = ""
    round: int = 0


class DiscussionTurn(BaseModel):
    """讨论时间线上的一条发言。"""

    round: int
    agent: str
    stance: Literal["maintain", "revise", "advocate", "moderator"]
    content: str
    score: Optional[float] = None
    score_delta: Optional[float] = None


class DiscussionMeta(BaseModel):
    rounds: int = 0
    convergence: Literal["consensus", "converged", "max_rounds"] = "consensus"
    devil_advocate_used: bool = False
    initial_mean: float = 0.0
    initial_std: float = 0.0
    final_mean: float = 0.0
    final_std: float = 0.0
    initial_scores: Dict[str, float] = Field(default_factory=dict)
    final_scores: Dict[str, float] = Field(default_factory=dict)


class DiscussionTranscript(BaseModel):
    """完整讨论记录（可审计、可回放）。"""

    turns: List[DiscussionTurn] = Field(default_factory=list)
    meta: DiscussionMeta = Field(default_factory=DiscussionMeta)

    def to_compact_dict(self) -> dict:
        return self.model_dump()


class OverallReport(BaseModel):
    """候选人精筛综合报告。"""

    candidate_id: str
    overall_score: float
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    recommendation_text: str = ""
    evidence: List[str] = Field(default_factory=list)
    agent_details: List[AgentEvaluationResult] = Field(default_factory=list)
    discussion: Optional[DiscussionTranscript] = None
