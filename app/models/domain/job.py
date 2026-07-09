from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Job:
    id: str
    tenant_id: str
    title: str
    jd_text: str
    jd_json: dict
    job_category: str
    created_at: Optional[datetime] = None