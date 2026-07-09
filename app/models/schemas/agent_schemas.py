from pydantic import BaseModel, Field
from typing import List, Dict

class AgentEvaluationResult(BaseModel):
    score: float = Field(..., ge=0, le=100)
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)

class OverallReport(BaseModel):
    candidate_id: str
    overall_score: float
    dimension_scores: Dict[str, float]
    recommendation_text: str
    evidence: List[str]
    agent_details: Dict[str, AgentEvaluationResult]