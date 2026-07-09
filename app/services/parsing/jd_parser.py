import json
import uuid
import logging
from app.infrastructure.llm_client import LLMClient
from app.infrastructure.guardrails import scan_input
from app.models.schemas.job_schema import JobDescription, JobCreateRequest
from app.db.repositories.job_repository import JobRepository
from app.db.session import get_db
from app.models.domain.job import Job
from app.core.exceptions import BusinessException

logger = logging.getLogger(__name__)

async def parse_jd(jd_text: str) -> JobDescription:
    """从原始JD文本中解析结构化职位描述"""
    if not jd_text or not jd_text.strip():
        raise BusinessException("JD text cannot be empty")

    scan_input(jd_text)  # 安全扫描

    llm = LLMClient()
    prompt = f"""从以下职位描述中提取信息，返回严格JSON格式，不要包含任何额外说明。JSON字段如下：
- title: 职位名称（字符串）
- hard_requirements: 硬性条件列表（学历、年限、技能等，字符串数组）
- soft_requirements: 软性要求列表（沟通、领导力等，字符串数组）
- skill_graph: 技能图谱列表（具体技术/工具名词，字符串数组）
- job_category: 岗位类别，必须为 tech/management/design/general 之一

职位描述：
{jd_text}
"""
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages)
    content = resp.choices[0].message.content.strip()
    # 尝试提取JSON
    try:
        # 有时LLM会在JSON外包裹 markdown 代码块
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        jd_dict = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM output as JSON: {content[:200]}")
        raise BusinessException("JD parsing failed: invalid LLM output format")

    return JobDescription.model_validate(jd_dict)

def save_job_to_db(tenant_id: str, jd_text: str, parsed: JobDescription) -> Job:
    with get_db() as conn:
        repo = JobRepository(conn)
        job = Job(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            title=parsed.title,
            jd_text=jd_text,
            jd_json=parsed.model_dump(),
            job_category=parsed.job_category.value,
            created_at=None
        )
        job.id = repo.insert(job)
        logger.info(f"Job saved: {job.id}")
        return job