import uuid
from app.infrastructure.redis_client import get_redis
from app.core.constants import LOCK_TIMEOUT_SECONDS

# Lua 脚本：仅当锁 token 匹配时才删除，保证原子释放（避免 get 后 delete 的竞态）
_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


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
        if not self._token:
            return
        # 原子释放：仅删除仍属于本锁的键
        self.redis.eval(_RELEASE_LUA, 1, self.key, self._token)

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"Failed to acquire lock: {self.key}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
