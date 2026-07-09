from pydantic import BaseModel, Field
from typing import List
from app.models.enums import JobCategory

class JobDescription(BaseModel):
    title: str = Field(..., description="职位名称")
    hard_requirements: List[str] = Field(default_factory=list, description="硬性条件")
    soft_requirements: List[str] = Field(default_factory=list, description="软性要求")
    skill_graph: List[str] = Field(default_factory=list, description="技能图谱")
    job_category: JobCategory = Field(..., description="岗位类别")

class JobCreateRequest(BaseModel):
    jd_text: str = Field(..., description="原始JD文本")
    language: str = Field(default="zh", description="语言")