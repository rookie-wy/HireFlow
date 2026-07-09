from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class MatchResult:
    id: str
    tenant_id: str
    job_id: str
    candidate_id: str
    overall_score: float
    dimension_scores: dict
    recommendation_text: str
    evidence: list
    created_at: Optional[datetime] = None