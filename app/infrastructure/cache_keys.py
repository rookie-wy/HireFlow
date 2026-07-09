from app.core.constants import CACHE_PREFIX_JOB, CACHE_PREFIX_CANDIDATE, IDEMPOTENT_KEY_PREFIX

def job_lock_key(job_id: str) -> str:
    return f"job:{job_id}:modify"

def session_key(session_id: str) -> str:
    return f"session:{session_id}"

def idempotent_key(prefix: str, unique_id: str) -> str:
    return f"{IDEMPOTENT_KEY_PREFIX}{prefix}:{unique_id}"