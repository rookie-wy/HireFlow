from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List, Dict
import os
from pathlib import Path
class Settings(BaseSettings):
    HF_ENDPOINT: str = "https://hf-mirror.com"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = ""
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/recruitment?charset=utf8mb4"
    REDIS_URL: str = "redis://localhost:6379/0"
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    OPENAI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    LITELLM_MODEL: str = "deepseek-chat"
    LLM_BACKUP_MODELS: List[str] = ["deepseek-chat"]
    LITELLM_API_BASE: str = "https://api.deepseek.com/v1"  # DeepSeek 兼容端点
    EMBEDDING_DEVICE: str = "cpu"
    RERANKER_DEVICE: str = "cpu"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    RATE_LIMIT_PER_MINUTE: str = "100/minute"
    CORS_ORIGINS: List[str] = ["http://localhost:8501", "http://localhost:3000"]
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PII_PATTERNS: Dict[str, str] = {
        "phone": r"1[3-9]\d{9}",
        "email": r"[^@\s]+@[^@\s]+\.[^@\s]+",
        "id_card": r"\d{17}[\dXx]"
    }
    ENABLE_PII_MASKING: bool = True
    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _ensure_jwt_secret(cls, v: str) -> str:
        if not v or v == "change-me":
            raise ValueError("JWT_SECRET_KEY 未设置或仍为默认值 'change-me'，请配置强随机密钥")
        return v

    class Config:
        # 用绝对路径定位 .env（src/.env），避免相对路径 ".env" 依赖当前工作目录：
        # 命令行 `cd src` 运行时 cwd 恰好是 src 能命中，但 PyCharm 直接运行时 cwd 常为
        # 项目根目录，相对路径找不到 .env 会导致 JWT_SECRET_KEY 等配置为空、启动崩溃。
        env_file = str(Path(__file__).resolve().parents[2] / ".env")

settings = Settings()
# 全局生效
os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT