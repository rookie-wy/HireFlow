from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    id: str
    tenant_id: str
    username: str
    role: str
    created_at: Optional[datetime] = None