from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class CostRecord:
    id: str
    tenant_id: str
    trace_id: str
    model_name: str
    tokens_prompt: int
    tokens_completion: int
    cost: float
    created_at: Optional[datetime] = None