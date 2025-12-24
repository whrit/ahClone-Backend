"""Celery tasks package."""

# Import tasks to register them with Celery
from app.tasks.ads import sync_ads_account  # noqa: F401
from app.tasks.maintenance import (  # noqa: F401
    cleanup_audit_runs,
    cleanup_old_data,
    health_check,
    vacuum_database,
)
