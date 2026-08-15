import os
import uuid
import tempfile
import logging
from app.infrastructure.models.mineru_client import parse_pdf as mineru_parse
from app.infrastructure.models.paddle_ocr_client import parse_image as paddle_parse
from app.infrastructure.llm_client import LLMClient
from app.infrastructure.guardrails import scan_input
from app.models.schemas.candidate_schema import CandidateProfile
from app.db.repositories.candidate_repository import CandidateRepository
from app.db.session import get_db
from app.models.domain.candidate import Candidate
from app.services.parsing.parser_utils import enforce_structured_output, save_uploaded_file, cleanup_file
from app.core.exceptions import BusinessException

logger = logging.getLogger(__name__)


async def parse_resume_pipeline(file_path: str, file_type: str) -> str:
    """pymupdf 优先 + OCR 后备，全部失败则返回空字符串"""
    # 1. pymupdf 提取 PDF 文本
    try:
        text = mineru_parse(file_path)
        if text and len(text.strip()) > 50:
            return text.strip()
    except Exception as e:
        logger.warning(f"MinerU failed: {e}")

    # 2. OCR 后备
    try:
        text = paddle_parse(file_path)
        if text and len(text.strip()) > 20:
            return text.strip()
    except Exception as e:
        logger.warning(f"PaddleOCR failed: {e}")

    logger.error("All resume parsing methods failed")
    return ""

@enforce_structured_output(CandidateProfile, max_retries=2)
async def extract_candidate_profile(raw_text: str) -> str:
    """调用 LLM 提取结构化候选人信息，返回原始 JSON 字符串"""
    raw_text = scan_input(raw_text)
    truncated_text = raw_text[:3000]
    llm = LLMClient()
    prompt = f"""从以下简历文本提取候选人信息，返回紧凑JSON（无换行、无缩进），结构如下：
{{"name":"姓名","email":"邮箱","phone":"电话","work_experience":[{{"company":"公司","title":"职位","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD或null","description":"职责描述"}}],"education":[{{"school":"学校","degree":"学位","major":"专业","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD或null"}}],"skills":["技能1","技能2"],"raw_text":"原文"}}
注意日期格式，缺少日期用null。直接输出JSON，不要任何说明。

简历文本：
{truncated_text}
"""
    messages = [{"role": "user", "content": prompt}]
    resp = llm.completion(messages, response_format={"type": "json_object"})
    content = resp.choices[0].message.content.strip()
    return content

async def process_resume_upload(file_content: bytes, filename: str, tenant_id: str) -> CandidateProfile:
    suffix = os.path.splitext(filename)[1].lower()
    tmp_path = save_uploaded_file(file_content, suffix)
    try:
        raw_text = await parse_resume_pipeline(tmp_path, suffix)
        if not raw_text:
            raise BusinessException("简历文件无法解析，请确认文件是否为可读的PDF或图片格式")

        # PII 脱敏（身份证号），email/phone 因业务需要保留
        raw_text = scan_input(raw_text)

        profile = await extract_candidate_profile(raw_text)

        # 技能标准化
        from app.services.parsing.skill_graph import match_skills
        profile.skills = match_skills(profile.skills)

        # 持久化到数据库
        with get_db() as conn:
            repo = CandidateRepository(conn)
            candidate = Candidate(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=profile.name,
                email=profile.email,
                phone=profile.phone,
                resume_text=raw_text,
                structured_json=profile.model_dump(),
                embedding_id=None,
                created_at=None
            )
            repo.insert(candidate)
            logger.info(f"Candidate saved: {candidate.id}")

        # 向量化候选人（同步调用，确保ChromaDB可用）
        try:
            from app.services.parsing.vectorization import vectorize_candidate
            vectorize_candidate(candidate.id, tenant_id, raw_text)
        except Exception as e:
            logger.warning(f"Vectorization failed for {candidate.id}: {e}")

        return profile
    finally:
        cleanup_file(tmp_path)