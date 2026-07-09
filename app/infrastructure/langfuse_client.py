import logging
from langfuse import Langfuse
from app.core.config import settings

langfuse_client = None

def init_langfuse():
    global langfuse_client
    if langfuse_client is None and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
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