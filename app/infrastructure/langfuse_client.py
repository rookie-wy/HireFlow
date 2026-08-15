import logging

try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:  # langfuse 未安装（后置项），观测日志跳过
    LANGFUSE_AVAILABLE = False

from app.core.config import settings

langfuse_client = None


def init_langfuse():
    global langfuse_client
    if (langfuse_client is None and LANGFUSE_AVAILABLE
            and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST
        )


def log_llm_call(model: str, messages: list, response):
    init_langfuse()
    if not langfuse_client:
        return
    try:
        trace = langfuse_client.trace(name="llm-completion")
        trace.span(
            name=model,
            input=messages,
            output=response
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Langfuse logging failed: {e}")
