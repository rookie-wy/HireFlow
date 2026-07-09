from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class InteractionLog:
    id: str
    tenant_id: str
    session_id: str
    user_id: str
    event_type: str
    target_id: Optional[str] = None
    feedback: Optional[str] = None
    summary_vector_id: Optional[str] = None
    created_at: Optional[datetime] = None