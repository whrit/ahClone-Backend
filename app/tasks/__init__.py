"""Celery tasks package."""

# Import tasks to register them with Celery
from app.tasks.ads import sync_ads_account  # noqa: F401
