from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings

# bcrypt 仅使用密码前 72 字节；bcrypt>=5.0 对超长输入抛 ValueError（旧版静默截断），
# 故此处显式截断，避免 RegisterRequest 允许的 128 字符上限触发异常。
_BCRYPT_MAX_BYTES = 72

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "sub": data.get("user_id"),
        "iat": now,
        "exp": expire,
        "iss": "ai-recruitment-agent",
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # 哈希格式非法或密码字节异常时视为不匹配，而非抛 500
        return False