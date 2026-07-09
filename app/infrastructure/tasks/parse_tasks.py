from celery import shared_task
from app.services.parsing.resume_parser import process_resume_upload
from app.db.repositories.candidate_repository import CandidateRepository
from app.db.session import get_db
import logging

logger = logging.getLogger(__name__)

@shared_task(name="parse_resume_task", queue="parse_resume")
def parse_resume_task(candidate_id: str, file_content: bytes, filename: str, tenant_id: str):
    try:
        profile = process_resume_upload(file_content, filename, tenant_id)
        # 更新 embedding_id (向量化工作也在此或独立任务完成)
        # ...
        logger.info(f"Async parse completed for candidate {candidate_id}")
        return {"status": "ok", "candidate_id": candidate_id}
    except Exception as e:
        logger.error(f"Async parse failed for {candidate_id}: {e}")
        return {"status": "error", "candidate_id": candidate_id}