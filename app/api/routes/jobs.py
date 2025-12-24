import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    JobRun,
    JobsPublic,
    JobStatus,
    JobStatusResponse,
    Message,
    Project,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    session: SessionDep, current_user: CurrentUser, job_id: uuid.UUID
) -> Any:
    """
    Get job status by ID.
    """
    job = session.get(JobRun, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check permissions - user must own the job
    if not current_user.is_superuser and (job.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    return JobStatusResponse(
        id=job.id,
        job_type=job.job_type.value,
        status=job.status,
        progress_pct=job.progress_pct,
        progress_message=job.progress_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
    )


@router.get("/project/{project_id}", response_model=JobsPublic)
def list_project_jobs(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> Any:
    """
    List recent jobs for a project.
    """
    # Verify project exists and user has access
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not current_user.is_superuser and (project.created_by_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    # Get jobs for the project
    count_statement = (
        select(func.count()).select_from(JobRun).where(JobRun.project_id == project_id)
    )
    count = session.exec(count_statement).one()

    statement = (
        select(JobRun)
        .where(JobRun.project_id == project_id)
        .order_by(JobRun.queued_at.desc())  # type: ignore
        .offset(skip)
        .limit(limit)
    )
    jobs = session.exec(statement).all()

    # Convert to response models
    job_responses = [
        JobStatusResponse(
            id=job.id,
            job_type=job.job_type.value,
            status=job.status,
            progress_pct=job.progress_pct,
            progress_message=job.progress_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_message=job.error_message,
        )
        for job in jobs
    ]

    return JobsPublic(data=job_responses, count=count)


@router.post("/{job_id}/cancel", response_model=Message)
def cancel_job(
    session: SessionDep, current_user: CurrentUser, job_id: uuid.UUID
) -> Message:
    """
    Cancel a running job.
    """
    job = session.get(JobRun, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check permissions
    if not current_user.is_superuser and (job.user_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    # Can only cancel queued or running jobs
    if job.status not in [JobStatus.QUEUED, JobStatus.RUNNING]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job.status.value}",
        )

    # Update job status
    job.status = JobStatus.CANCELLED
    job.finished_at = datetime.utcnow()
    job.error_message = "Job cancelled by user"

    session.add(job)
    session.commit()
    session.refresh(job)

    # TODO: Send cancel signal to Celery task if celery_task_id is set
    # if job.celery_task_id:
    #     celery_app.control.revoke(job.celery_task_id, terminate=True)

    return Message(message="Job cancelled successfully")
