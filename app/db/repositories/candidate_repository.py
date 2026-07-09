import uuid
import json
from typing import Optional
from app.db.repositories.base_repository import BaseRepository
from app.models.domain.candidate import Candidate

class CandidateRepository(BaseRepository):
    def insert(self, candidate: Candidate) -> str:
        return self.upsert(candidate)

    def upsert(self, candidate: Candidate) -> str:
        """
        如果 (tenant_id, email) 已存在则更新，否则插入。
        返回 candidate.id。
        """
        if not candidate.id:
            candidate.id = str(uuid.uuid4())

        # 先检查是否存在
        existing = self.find_by_email(candidate.email)
        if existing:
            # 更新
            query = """
                UPDATE candidates 
                SET name=%s, phone=%s, resume_text=%s, structured_json=%s, embedding_id=%s
                WHERE id=%s AND tenant_id=%s
            """
            self._execute(query, (
                candidate.name,
                candidate.phone,
                candidate.resume_text,
                json.dumps(candidate.structured_json, default=str) if candidate.structured_json else None,
                candidate.embedding_id,
                existing.id,
                self.tenant_id
            ))
            return existing.id
        else:
            # 插入
            query = """
                INSERT INTO candidates (id, tenant_id, name, email, phone, resume_text, structured_json, embedding_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            self._execute(query, (
                candidate.id,
                self.tenant_id,
                candidate.name,
                candidate.email,
                candidate.phone,
                candidate.resume_text,
                json.dumps(candidate.structured_json, default=str) if candidate.structured_json else None,
                candidate.embedding_id
            ))
            return candidate.id

    def find_by_email(self, email: str) -> Optional[Candidate]:
        query = "SELECT id, tenant_id, name, email, phone, resume_text, structured_json, embedding_id, created_at FROM candidates WHERE email = %s AND tenant_id = %s"
        row = self._fetchone(query, (email, self.tenant_id))
        if row:
            return Candidate(
                id=row[0],
                tenant_id=row[1],
                name=row[2],
                email=row[3],
                phone=row[4],
                resume_text=row[5],
                structured_json=json.loads(row[6]) if row[6] else {},
                embedding_id=row[7],
                created_at=row[8]
            )
        return None

    def find_by_id(self, candidate_id: str) -> Optional[Candidate]:
        query = "SELECT id, tenant_id, name, email, phone, resume_text, structured_json, embedding_id, created_at FROM candidates WHERE id = %s AND tenant_id = %s"
        row = self._fetchone(query, (candidate_id, self.tenant_id))
        if row:
            return Candidate(
                id=row[0],
                tenant_id=row[1],
                name=row[2],
                email=row[3],
                phone=row[4],
                resume_text=row[5],
                structured_json=json.loads(row[6]) if row[6] else {},
                embedding_id=row[7],
                created_at=row[8]
            )
        return None

    def list_by_tenant(self) -> list[Candidate]:
        query = "SELECT id, tenant_id, name, email, phone, resume_text, structured_json, embedding_id, created_at FROM candidates WHERE tenant_id = %s"
        rows = self._fetchall(query, (self.tenant_id,))
        candidates = []
        for row in rows:
            candidates.append(Candidate(
                id=row[0],
                tenant_id=row[1],
                name=row[2],
                email=row[3],
                phone=row[4],
                resume_text=row[5],
                structured_json=json.loads(row[6]) if row[6] else {},
                embedding_id=row[7],
                created_at=row[8]
            ))
        return candidates

    def delete(self, candidate_id: str):
        query = "DELETE FROM candidates WHERE id = %s AND tenant_id = %s"
        self._execute(query, (candidate_id, self.tenant_id))