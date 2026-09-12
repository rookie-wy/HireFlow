"""Agent 服务错误体系与日志。"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional


class AgentError(Exception):
    """业务错误基类：code 段与 backend 错误码对齐。"""

    code = 50000
    http_status = 500
    message = "服务内部错误"

    def __init__(self, message: Optional[str] = None, *, cause: Optional[Exception] = None) -> None:
        self.message = message or self.message
        self.cause = cause
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class BadRequestError(AgentError):
    code = 40000
    http_status = 400
    message = "请求参数不合法"


class ParseError(AgentError):
    code = 50004
    http_status = 502
    message = "文档解析失败"


class LLMError(AgentError):
    code = 50003
    http_status = 502
    message = "LLM 调用失败"


class UpstreamError(AgentError):
    code = 50002
    http_status = 502
    message = "外部依赖不可用"


class JSONTraceIdFilter(logging.Filter):
    """注入 trace_id。"""

    def __init__(self) -> None:
        super().__init__()
        self.trace_id = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = self.trace_id
        return True


_trace_filter = JSONTraceIdFilter()


def set_trace_id(trace_id: str) -> None:
    _trace_filter.trace_id = trace_id or "-"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    prod = os.environ.get("APP_ENV") == "production"
    handler: logging.Handler
    if prod:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(trace_id)s] %(levelname)s %(name)s: %(message)s")
        )
    handler.addFilter(_trace_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    # 默认 INFO：DEBUG 级会把 httpx/httpcore/openai 的每次请求头与响应体都写进日志，
    # 实测一次筛选刷出上万行同步写盘日志，把单次筛选拖到 150s+（看起来像"模型很慢"）。
    # 需要第三方库细节时显式设 LOG_LEVEL=DEBUG。
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    # 话痨第三方库：无论根级别如何都压到 WARNING（逐请求/逐响应体日志没有保留价值）
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "chromadb", "asyncio", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
