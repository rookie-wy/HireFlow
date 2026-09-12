"""解析服务数据契约（与 backend agenttypes 一一对应）。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

JobCategory = Literal["tech", "management", "design", "general"]


class JobDescription(BaseModel):
    title: str = ""
    hard_requirements: List[str] = Field(default_factory=list)
    soft_requirements: List[str] = Field(default_factory=list)
    skill_graph: List[str] = Field(default_factory=list)
    job_category: JobCategory = "general"


class WorkExperience(BaseModel):
    company: str = ""
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""


class CandidateProfile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    work_experience: List[WorkExperience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    raw_text: str = ""
