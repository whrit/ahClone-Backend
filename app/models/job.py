import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    """Job execution status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Type of background job."""

    AUDIT = "audit"
    GSC_SYNC = "gsc_sync"
    GSC_BACKFILL = "gsc_backfill"
    SERP_REFRESH = "serp_refresh"
    LINKS_INGEST = "links_ingest"
    ADS_SYNC = "ads_sync"


# Database model
class JobRun(SQLModel, table=True):
    """Job run tracking for background tasks."""

    __tablename__ = "job_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_type: JobType
    celery_task_id: str | None = None

    project_id: uuid.UUID | None = Field(
        default=None, foreign_key="projects.id", index=True, ondelete="CASCADE"
    )
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="CASCADE")

    status: JobStatus = JobStatus.QUEUED
    progress_pct: int = 0
    progress_message: str | None = None

    queued_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = None
    config_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


# API Response models
class JobStatusResponse(SQLModel):
    """Response model for job status."""

    id: uuid.UUID
    job_type: str
    status: JobStatus
    progress_pct: int
    progress_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None


class JobsPublic(SQLModel):
    """Response model for listing multiple jobs."""

    data: list[JobStatusResponse]
    count: int
