from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Candidate:
    id: str
    tenant_id: str
    name: str
    email: str
    phone: str
    resume_text: str
    structured_json: dict
    embedding_id: Optional[str] = None
    created_at: Optional[datetime] = None