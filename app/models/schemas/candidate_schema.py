from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: datetime
    end_date: Optional[datetime] = None
    description: str

class Education(BaseModel):
    school: str
    degree: str
    major: str
    start_date: datetime
    end_date: Optional[datetime] = None

class CandidateProfile(BaseModel):
    name: str
    email: str
    phone: str
    work_experience: List[WorkExperience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    raw_text: str