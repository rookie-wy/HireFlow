from app.infrastructure.redis_client import get_redis
from app.core.constants import LOCK_TIMEOUT_SECONDS
import uuid
import time

class RedisLock:
    def __init__(self, key: str, timeout: int = LOCK_TIMEOUT_SECONDS):
        self.redis = get_redis()
        self.key = f"lock:{key}"
        self.timeout = timeout
        self._token = None

    def acquire(self) -> bool:
        self._token = str(uuid.uuid4())
        return self.redis.set(self.key, self._token, nx=True, ex=self.timeout)

    def release(self):
        if self._token and self.redis.get(self.key) == self._token:
            self.redis.delete(self.key)