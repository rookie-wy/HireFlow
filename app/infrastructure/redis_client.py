import redis
from app.core.config import settings
from app.core.exceptions import InfrastructureException

redis_pool = None

def get_redis():
    global redis_pool
    if redis_pool is None:
        try:
            redis_pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=20,
                socket_timeout=5,
                socket_connect_timeout=5
            )
        except Exception as e:
            raise InfrastructureException(f"Redis connection failed: {e}")
    return redis.Redis(connection_pool=redis_pool)

def close_redis():
    global redis_pool
    if redis_pool:
        redis_pool.disconnect()