import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pybreaker import CircuitBreaker, CircuitBreakerError
from app.core.config import settings
from app.core.exceptions import LLMException
import logging

logger = logging.getLogger(__name__)

# 熔断器
breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=60
)

class LLMClient:
    def __init__(self, model: str = None):
        # 默认使用配置的模型，并自动添加 provider 前缀
        base_model = model or settings.LITELLM_MODEL
        if "deepseek" in base_model and not base_model.startswith("deepseek/"):
            self.model = f"deepseek/{base_model}"   # 正确的 LiteLLM 格式
        else:
            self.model = base_model

        # 设置 API Key：优先 DeepSeek 专用 key，回退到通用 OpenAI key
        self.api_key = settings.DEEPSEEK_API_KEY or settings.OPENAI_API_KEY
        litellm.api_key = self.api_key
        # 可选：显式设置 provider 的 base URL
        if "deepseek" in self.model:
            litellm.deepseek_api_base = "https://api.deepseek.com/v1"
            litellm.deepseek_key = self.api_key

    def completion(self, messages: list, temperature=0.1, response_format=None, max_tokens=1000, **kwargs):
        # breaker 打开时会在 _do_completion 之外抛 CircuitBreakerError，这里捕获并降级
        try:
            return self._do_completion(messages, temperature, response_format, max_tokens, **kwargs)
        except CircuitBreakerError:
            logger.warning("LLM circuit breaker open, falling back")
            return self._fallback(messages)

    @breaker
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(LLMException),
        reraise=True
    )
    def _do_completion(self, messages, temperature=0.1, response_format=None, max_tokens=1000, **kwargs):
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                api_key=self.api_key,
                **kwargs
            )
            return response
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise LLMException(f"LLM error: {str(e)}")

    def _fallback(self, messages):
        # 降级链：尝试备用模型（未显式带 provider 前缀的默认按 deepseek 处理）
        for backup in settings.LLM_BACKUP_MODELS:
            if backup == self.model.split("/")[-1]:
                continue
            try:
                backup_model = backup if "/" in backup else f"deepseek/{backup}"
                response = litellm.completion(model=backup_model, messages=messages, api_key=self.api_key)
                return response
            except Exception as e:
                logger.error(f"Backup model {backup} failed: {e}")
        raise LLMException("All LLM models failed")