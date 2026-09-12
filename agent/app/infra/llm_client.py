"""LLM 网关：统一调用入口，内置重试、熔断、备用模型与成本计量。

成本计量通过 `consume_usage` 回调注入（由 API 层把 usage 汇入响应事件，
backend 统一落 cost_records，保持「Python 不写 MySQL」的边界）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from openai import OpenAI

from app.core.config import Settings, get_settings
from app.core.metrics import inc, observe
from app.core.errors import LLMError, get_logger

log = get_logger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_prompt: int = 0
    tokens_completion: int = 0

    @property
    def cost(self) -> float:
        s: Settings = get_settings()
        return (
            self.tokens_prompt / 1_000_000 * s.llm_price_prompt_per_m
            + self.tokens_completion / 1_000_000 * s.llm_price_completion_per_m
        )


@dataclass
class _Breaker:
    """进程内熔断器：连续失败 N 次打开，冷却后放行探测。"""

    fail_max: int
    reset_timeout: int
    _consecutive_failures: int = 0
    _opened_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at == 0.0:
                return True
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                # 半开：放行探测，失败将重新计时
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_max:
                self._opened_at = time.monotonic()
                log.warning("LLM breaker OPEN for %ss after %d failures", self.reset_timeout, self._consecutive_failures)


class LLMClient:
    """OpenAI 兼容客户端（DeepSeek）。所有业务 LLM 调用必须经过此处。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        s = settings or get_settings()
        self._settings = s
        # 无 key 时允许构造（延迟到调用时报错），保证健康检查等服务可启动
        self._client = OpenAI(api_key=s.llm_api_key or "sk-empty", base_url=s.llm_base_url, timeout=s.llm_timeout_seconds)
        self._breaker = _Breaker(fail_max=s.llm_breaker_fail_max, reset_timeout=s.llm_breaker_reset_timeout)
        self._usage_listeners: List[Callable[[LLMResponse], None]] = []

    # ---- 成本计量 ----
    def on_usage(self, listener: Callable[[LLMResponse], None]) -> None:
        self._usage_listeners.append(listener)

    def _emit_usage(self, resp: LLMResponse) -> None:
        for listener in self._usage_listeners:
            try:
                listener(resp)
            except Exception:  # noqa: BLE001 计量失败不影响主流程
                log.exception("usage listener failed")

    # ---- 核心调用 ----
    def chat(
        self,
        messages: List[dict],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """带熔断 + 重试 + 备用模型降级的补全调用。"""
        s = self._settings
        temperature = s.llm_temperature if temperature is None else temperature
        max_tokens = s.llm_max_tokens if max_tokens is None else max_tokens

        if not self._breaker.allow():
            raise LLMError("LLM 熔断中，请稍后重试")
        if not self._settings.llm_api_key:
            raise LLMError("LLM_API_KEY 未配置")

        models: List[str] = [s.llm_model] + [m for m in s.llm_backup_models if m != s.llm_model]
        last_err: Optional[Exception] = None

        for model in models:
            for attempt in range(1, s.llm_retry_attempts + 1):
                try:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if response_format is not None:
                        kwargs["response_format"] = response_format
                    call_started = time.perf_counter()
                    completion = self._client.chat.completions.create(**kwargs)
                    usage = getattr(completion, "usage", None)
                    resp = LLMResponse(
                        content=completion.choices[0].message.content or "",
                        model=model,
                        tokens_prompt=getattr(usage, "prompt_tokens", 0) or 0,
                        tokens_completion=getattr(usage, "completion_tokens", 0) or 0,
                    )
                    self._breaker.record_success()
                    self._emit_usage(resp)
                    # 可观测性（O6）：LLM 调用次数/耗时/token/成本，按模型与结果维度打点
                    elapsed = time.perf_counter() - call_started
                    inc("llm_calls_total", status="ok", model=model)
                    observe("llm_call_seconds", elapsed, model=model)
                    inc("llm_tokens_total", resp.tokens_prompt, kind="prompt", model=model)
                    inc("llm_tokens_total", resp.tokens_completion, kind="completion", model=model)
                    inc("llm_cost_usd_total", resp.cost, model=model)
                    return resp
                except Exception as exc:  # noqa: BLE001 网关统一兜底
                    last_err = exc
                    inc("llm_calls_total", status="failed", model=model)
                    log.warning(
                        "LLM call failed model=%s attempt=%d/%d err=%s", model, attempt, s.llm_retry_attempts, exc
                    )
                    time.sleep(min(2 ** (attempt - 1), 8))

        self._breaker.record_failure()
        inc("llm_breaker_open_total")
        raise LLMError(cause=last_err)

    def chat_json(self, messages: List[dict], **kwargs: Any) -> tuple[dict, LLMResponse]:
        """要求 JSON 输出的调用：优先 response_format，失败用 json_repair 兜底。"""
        import json_repair

        kwargs.setdefault("response_format", {"type": "json_object"})
        resp = self.chat(messages, **kwargs)
        data = json_repair.loads(resp.content)
        if not isinstance(data, dict):
            raise LLMError(f"期望 JSON 对象输出，实际: {type(data).__name__}")
        return data, resp


_client: Optional[LLMClient] = None
_client_lock = threading.Lock()


def get_llm_client() -> LLMClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = LLMClient()
        return _client
