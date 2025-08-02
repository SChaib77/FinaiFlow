from celery import Celery
from celery.signals import worker_init, worker_shutdown
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# Create Celery app
celery_app = Celery(
    "finaiflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.email",
        "app.tasks.notifications", 
        "app.tasks.reports",
        "app.tasks.cleanup"
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Task routing
celery_app.conf.task_routes = {
    "app.tasks.email.*": {"queue": "email"},
    "app.tasks.notifications.*": {"queue": "notifications"},
    "app.tasks.reports.*": {"queue": "reports"},
    "app.tasks.cleanup.*": {"queue": "cleanup"},
}

# Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "cleanup-expired-tokens": {
        "task": "app.tasks.cleanup.cleanup_expired_tokens",
        "schedule": 3600.0,  # Every hour
    },
    "cleanup-old-audit-logs": {
        "task": "app.tasks.cleanup.cleanup_old_audit_logs", 
        "schedule": 86400.0,  # Every day
    },
    "send-usage-reports": {
        "task": "app.tasks.reports.send_usage_reports",
        "schedule": 604800.0,  # Every week
    },
}


@worker_init.connect
def worker_init_handler(sender=None, conf=None, **kwargs):
    """Initialize worker"""
    logger.info("Celery worker starting")


@worker_shutdown.connect  
def worker_shutdown_handler(sender=None, **kwargs):
    """Cleanup on worker shutdown"""
    logger.info("Celery worker shutting down")