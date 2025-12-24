"""Celery app configuration for the SEO platform."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings


def create_celery_app() -> Celery:
    """
    Factory function to create and configure the Celery application.

    Returns:
        Celery: Configured Celery application instance
    """
    celery_app = Celery(
        "seo_platform",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )

    # Configure Celery
    celery_app.conf.update(
        # Serialization settings
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",

        # Time limit settings (in seconds)
        task_time_limit=3600,  # 1 hour hard limit
        task_soft_time_limit=3300,  # 55 minutes soft limit

        # Task execution settings
        task_acks_late=True,  # Acknowledge tasks after execution
        task_reject_on_worker_lost=True,  # Re-queue tasks if worker dies
        worker_prefetch_multiplier=1,  # Fetch one task at a time

        # Result backend settings
        result_expires=86400,  # Results expire after 24 hours

        # Timezone configuration
        timezone="UTC",
        enable_utc=True,

        # Task routing configuration
        task_routes={
            "app.tasks.audit.*": {"queue": "default"},
            "app.tasks.gsc.*": {"queue": "default"},
            "app.tasks.serp.*": {"queue": "default"},
            "app.tasks.links.*": {"queue": "low"},
            "app.tasks.ads.*": {"queue": "default"},
        },

        # Beat schedule for periodic tasks
        beat_schedule={
            "gsc-daily-sync": {
                "task": "app.tasks.gsc.daily_sync",
                "schedule": crontab(hour=2, minute=0),  # 2:00 AM daily
            },
            "serp-daily-refresh": {
                "task": "app.tasks.serp.daily_refresh",
                "schedule": crontab(hour=3, minute=0),  # 3:00 AM daily
            },
            "ads-daily-sync": {
                "task": "app.tasks.ads.daily_sync",
                "schedule": crontab(hour=4, minute=0),  # 4:00 AM daily
            },
            "cleanup-old-data": {
                "task": "app.tasks.maintenance.cleanup_old_data",
                "schedule": crontab(hour=5, minute=0),  # 5:00 AM daily
            },
            "vacuum-database": {
                "task": "app.tasks.maintenance.vacuum_database",
                "schedule": crontab(hour=6, minute=0, day_of_week=0),  # 6:00 AM on Sundays
            },
            "audit-weekly": {
                "task": "app.tasks.audit.weekly_audit",
                "schedule": crontab(hour=1, minute=0, day_of_week=0),  # 1:00 AM on Sundays
            },
        },
    )

    # Auto-discover tasks from task modules
    celery_app.autodiscover_tasks(
        packages=[
            "app.tasks.audit",
            "app.tasks.gsc",
            "app.tasks.serp",
            "app.tasks.links",
            "app.tasks.ads",
            "app.tasks.maintenance",
        ],
        force=True,
    )

    return celery_app


# Create the Celery app instance
celery_app = create_celery_app()
