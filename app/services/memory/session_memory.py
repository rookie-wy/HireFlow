import json
from app.infrastructure.redis_client import get_redis
from app.core.constants import SESSION_TTL
from app.infrastructure.tasks.memory_tasks import persist_session_snapshot

class SessionMemory:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.redis = get_redis()
        self.key = f"session:{session_id}"

    def save(self, state: dict):
        self.redis.hset(self.key, mapping=state)
        self.redis.expire(self.key, SESSION_TTL)
        # 异步持久化快照
        persist_session_snapshot.delay(self.session_id, state)

    def load(self) -> dict:
        data = self.redis.hgetall(self.key)
        if not data:
            return {}
        return {k.decode(): v.decode() for k, v in data.items()}

    def delete(self):
        self.redis.delete(self.key)