import logging
import uuid
from contextvars import ContextVar
from typing import Optional

trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_var.get() or "no-trace"
        return True

def setup_logging():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(trace_id)s] %(levelname)s %(name)s: %(message)s')
    logger = logging.getLogger()
    logger.addFilter(TraceIdFilter())