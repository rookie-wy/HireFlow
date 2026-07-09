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

        # 设置 API Key 和 Base URL（若需要）
        litellm.api_key = settings.OPENAI_API_KEY
        # 可选：显式设置 provider 的 base URL
        if "deepseek" in self.model:
            litellm.deepseek_api_base = "https://api.deepseek.com/v1"
            litellm.deepseek_key = settings.OPENAI_API_KEY

    @breaker
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMException, CircuitBreakerError)),
        reraise=True
    )
    def completion(self, messages: list, temperature=0.1, response_format=None, max_tokens=1000, **kwargs):
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                api_key=settings.OPENAI_API_KEY,  # 备用模型降级逻辑（可选）
                **kwargs
            )
            return response
        except CircuitBreakerError:
            logger.warning("LLM circuit breaker open")
            return self._fallback(messages)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise LLMException(f"LLM error: {str(e)}")

    def _fallback(self, messages):
        # 降级链：尝试备用模型（仍使用相同 provider）
        for backup in settings.LLM_BACKUP_MODELS:
            if backup == self.model.split("/")[-1]:
                continue
            try:
                backup_model = f"deepseek/{backup}" if "deepseek" in backup else backup
                response = litellm.completion(model=backup_model, messages=messages)
                return response
            except Exception as e:
                logger.error(f"Backup model {backup} failed: {e}")
        raise LLMException("All LLM models failed")