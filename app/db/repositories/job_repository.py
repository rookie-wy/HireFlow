import json
import uuid
from typing import Optional
from app.db.repositories.base_repository import BaseRepository
from app.models.domain.job import Job

class JobRepository(BaseRepository):
    def insert(self, job: Job) -> str:
        if not job.id:
            job.id = str(uuid.uuid4())
        query = """
            INSERT INTO jobs (id, tenant_id, title, jd_text, jd_json, job_category)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        self._execute(query, (
            job.id,
            job.tenant_id or self.tenant_id,
            job.title,
            job.jd_text,
            json.dumps(job.jd_json,default=str) if job.jd_json else None,
            job.job_category
        ))
        return job.id

    def find_by_id(self, job_id: str) -> Optional[Job]:
        query = "SELECT id, tenant_id, title, jd_text, jd_json, job_category, created_at FROM jobs WHERE id = %s AND tenant_id = %s"
        row = self._fetchone(query, (job_id, self.tenant_id))
        if row:
            return Job(
                id=row[0],
                tenant_id=row[1],
                title=row[2],
                jd_text=row[3],
                jd_json=json.loads(row[4]) if row[4] else {},
                job_category=row[5],
                created_at=row[6]
            )
        return None

    def list_all(self) -> list[Job]:
        query = "SELECT id, tenant_id, title, jd_text, jd_json, job_category, created_at FROM jobs WHERE tenant_id = %s ORDER BY created_at DESC"
        rows = self._fetchall(query, (self.tenant_id,))
        jobs = []
        for row in rows:
            jobs.append(Job(
                id=row[0],
                tenant_id=row[1],
                title=row[2],
                jd_text=row[3],
                jd_json=json.loads(row[4]) if row[4] else {},
                job_category=row[5],
                created_at=row[6]
            ))
        return jobs