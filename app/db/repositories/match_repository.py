import json
import uuid
from typing import Optional
from app.db.repositories.base_repository import BaseRepository
from app.models.schemas.agent_schemas import OverallReport

class MatchRepository(BaseRepository):
    def insert_from_report(self, report: OverallReport, tenant_id: str, job_id: str):
        match_id = str(uuid.uuid4())
        query = """
            INSERT INTO match_results (id, tenant_id, job_id, candidate_id, overall_score, dimension_scores, recommendation_text, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        self._execute(query, (
            match_id,
            tenant_id,
            job_id,
            report.candidate_id,
            report.overall_score,
            json.dumps(report.dimension_scores,default=str) if report.dimension_scores else None,
            report.recommendation_text,
            json.dumps(report.evidence,default=str) if report.evidence else None
        ))
        return match_id

    def find_by_id(self, match_id: str) -> Optional[dict]:
        query = "SELECT * FROM match_results WHERE id = %s AND tenant_id = %s"
        row = self._fetchone(query, (match_id, self.tenant_id))
        if row:
            return {
                "id": row[0],
                "tenant_id": row[1],
                "job_id": row[2],
                "candidate_id": row[3],
                "overall_score": row[4],
                "dimension_scores": json.loads(row[5]) if row[5] else {},
                "recommendation_text": row[6],
                "evidence": json.loads(row[7]) if row[7] else [],
                "created_at": row[8]
            }
        return None

    def list_by_job(self, job_id: str) -> list[dict]:
        query = "SELECT * FROM match_results WHERE job_id = %s AND tenant_id = %s ORDER BY overall_score DESC"
        rows = self._fetchall(query, (job_id, self.tenant_id))
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "tenant_id": row[1],
                "job_id": row[2],
                "candidate_id": row[3],
                "overall_score": row[4],
                "dimension_scores": json.loads(row[5]) if row[5] else {},
                "recommendation_text": row[6],
                "evidence": json.loads(row[7]) if row[7] else [],
                "created_at": row[8]
            })
        return results