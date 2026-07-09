import json
import uuid
from datetime import datetime
from app.db.repositories.base_repository import BaseRepository

class InteractionRepository(BaseRepository):
    def insert(self, id: str, tenant_id: str, session_id: str, user_id: str, event_type: str,
               target_id: str = None, feedback: str = None, summary_vector_id: str = None, created_at: datetime = None):
        if not id:
            id = str(uuid.uuid4())
        query = """
            INSERT INTO interaction_log (id, tenant_id, session_id, user_id, event_type, target_id, feedback, summary_vector_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self._execute(query, (
            id,
            tenant_id,
            session_id,
            user_id,
            event_type,
            target_id,
            feedback,
            summary_vector_id,
            created_at or datetime.utcnow()
        ))
        return id

    def get_high_potential_ids(self, tenant_id: str, exclude_job_id: str, limit=5):
        # 注意：实际业务中可能需要联表，这里提供简化的示例实现
        query = """
            SELECT DISTINCT target_id FROM interaction_log
            WHERE tenant_id = %s AND feedback = 'suitable' AND target_id IS NOT NULL
            AND target_id NOT IN (
                SELECT target_id FROM interaction_log WHERE tenant_id = %s AND feedback = 'not_suitable' AND target_id = %s
            )
            LIMIT %s
        """
        rows = self._fetchall(query, (tenant_id, tenant_id, exclude_job_id, limit))
        return [row[0] for row in rows]