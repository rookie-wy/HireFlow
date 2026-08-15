"""Celery 兼容层。

celery 属于后置依赖，未安装时用占位任务替代，使异步任务退化为空操作，
避免 import 失败。真正规模化时安装 celery 即可无缝切换。
"""
import logging

logger = logging.getLogger(__name__)

try:
    from celery import shared_task as _celery_shared_task
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False


class _DummyTask:
    def __init__(self, func):
        self.func = func

    def delay(self, *args, **kwargs):
        logger.debug("celery 未安装，跳过异步任务 %s", getattr(self.func, "__name__", "task"))
        return None

    def apply_async(self, *args, **kwargs):
        return self.delay(*args, **kwargs)


def shared_task_compat(*dec_args, **dec_kwargs):
    """替代 @shared_task 与 @shared_task(name=..., queue=...) 两种用法。"""
    def decorator(func):
        if CELERY_AVAILABLE:
            return _celery_shared_task(*dec_args, **dec_kwargs)(func)
        return _DummyTask(func)
    return decorator
