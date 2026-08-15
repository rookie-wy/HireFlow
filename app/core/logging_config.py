import logging
import os
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from typing import Optional

trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

_LOG_FORMAT = '%(asctime)s [%(trace_id)s] %(levelname)s %(name)s: %(message)s'


class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_var.get() or "no-trace"
        return True


def setup_logging():
    formatter = logging.Formatter(_LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 注意：TraceIdFilter 必须挂在 handler 上而非 root logger —— logging 的
    # Logger.filter 只检查当前 logger 自己的 filters，子 logger（如 app.db.session）
    # 产生的记录不会经过 root 的 filter，会导致 %(trace_id)s 字段缺失抛 KeyError。
    trace_filter = TraceIdFilter()

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(trace_filter)
    root.addHandler(console)

    # 文件输出（轮转：单文件 10MB，保留 5 份）
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(trace_filter)
    root.addHandler(file_handler)
