import json
import uuid
from app.db.repositories.base_repository import BaseRepository
from app.models.domain.cost_record import CostRecord

class CostRepository(BaseRepository):
    def insert(self, record: CostRecord) -> str:
        if not record.id:
            record.id = str(uuid.uuid4())
        query = """
            INSERT INTO cost_records (id, tenant_id, trace_id, model_name, tokens_prompt, tokens_completion, cost)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        self._execute(query, (
            record.id,
            self.tenant_id,
            record.trace_id,
            record.model_name,
            record.tokens_prompt,
            record.tokens_completion,
            record.cost
        ))
        return record.id