from app.infrastructure.redis_client import get_redis
from app.services.memory.interaction_logger import InteractionLogger

def process_feedback(tenant_id: str, user_id: str, candidate_id: str, feedback: str, session_id: str):
    # 记录交互日志
    InteractionLogger.log_event(
        tenant_id=tenant_id,
        session_id=session_id,
        user_id=user_id,
        event_type="feedback",
        target_id=candidate_id,
        feedback=feedback
    )
    # 更新用户即时排序偏好（Redis）
    redis = get_redis()
    user_key = f"user:{user_id}:prefs"
    increment = 0
    if feedback == "suitable":
        increment = 0.1
    elif feedback == "not_suitable":
        increment = -0.1
    # 存储为zset或hash
    redis.hincrbyfloat(user_key, candidate_id, increment)

def apply_personalized_boost(user_id: str, candidate_scores: dict) -> dict:
    """在精筛结果上应用用户偏好"""
    redis = get_redis()
    user_key = f"user:{user_id}:prefs"
    if not redis.exists(user_key):
        return candidate_scores
    boosts = redis.hgetall(user_key)
    for cid, score in candidate_scores.items():
        boost_val = float(boosts.get(cid.encode(), 0))
        candidate_scores[cid] = score * (1 + boost_val)
    return candidate_scores