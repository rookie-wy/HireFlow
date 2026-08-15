from app.core.config import settings

try:
    from celery import Celery
    CELERY_AVAILABLE = True
except ImportError:  # celery 未安装（后置项），不启动 worker
    CELERY_AVAILABLE = False

if CELERY_AVAILABLE:
    celery_app = Celery(
        'recruitment',
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
        include=['app.tasks']  # 未来任务模块
    )
    celery_app.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='Asia/Shanghai',
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_default_queue='default',
        task_queues={
            'parse_resume': {'exchange': 'parse_resume', 'routing_key': 'parse_resume'},
            'send_email': {'exchange': 'send_email', 'routing_key': 'send_email'},
            'generate_summary': {'exchange': 'generate_summary', 'routing_key': 'generate_summary'},
        },
        task_routes={
            'app.tasks.parse_resume.*': {'queue': 'parse_resume'},
            'app.tasks.send_email.*': {'queue': 'send_email'},
            'app.tasks.generate_summary.*': {'queue': 'generate_summary'},
        }
    )
else:
    celery_app = None
