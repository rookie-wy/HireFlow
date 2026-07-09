import functools
import logging
import os
import tempfile
import json
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

from json_repair import repair_json

def _auto_fix_json(json_str: str) -> str:
    if json_str.startswith("```"):
        parts = json_str.split("```", 2)
        if len(parts) >= 2:
            json_str = parts[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        json_str = json_str.strip()
    return repair_json(json_str)

def enforce_structured_output(model_cls: BaseModel, max_retries=2):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    if isinstance(result, model_cls):
                        return result
                    if isinstance(result, str):
                        fixed = _auto_fix_json(result)
                        return model_cls.model_validate(json.loads(fixed))
                    if isinstance(result, dict):
                        return model_cls.model_validate(result)
                    return model_cls.model_validate(result)
                except (ValidationError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Structured output validation failed (attempt {attempt+1}): {e}")
                    last_exc = e
            raise ValueError(f"Failed to parse structured output after {max_retries} retries") from last_exc
        return wrapper
    return decorator

def save_uploaded_file(content: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, 'wb') as f:
        f.write(content)
    return path

def cleanup_file(path: str):
    try:
        os.unlink(path)
    except OSError:
        logger.warning(f"Failed to remove temp file: {path}")