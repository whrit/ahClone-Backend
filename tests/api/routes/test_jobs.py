import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from tests.utils.project import create_random_project


def test_get_job_status(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting job status by ID."""
    # Create a project first
    project = create_random_project(db, owner_id=normal_user.id)

    # Create a job run directly in the database
    from app.models.job import JobRun, JobStatus, JobType

    job = JobRun(
        job_type=JobType.AUDIT,
        project_id=project.id,
        user_id=normal_user.id,
        status=JobStatus.RUNNING,
        progress_pct=50,
        progress_message="Processing pages...",
        celery_task_id="test-task-123",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Get job status
    response = client.get(
        f"{settings.API_V1_STR}/jobs/{job.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(job.id)
    assert content["job_type"] == "audit"
    assert content["status"] == "running"
    assert content["progress_pct"] == 50
    assert content["progress_message"] == "Processing pages..."


def test_get_job_status_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test getting a non-existent job."""
    response = client.get(
        f"{settings.API_V1_STR}/jobs/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Job not found"


def test_list_project_jobs(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing recent jobs for a project."""
    # Create a project
    project = create_random_project(db, owner_id=normal_user.id)

    # Create multiple job runs
    from app.models.job import JobRun, JobStatus, JobType

    job1 = JobRun(
        job_type=JobType.AUDIT,
        project_id=project.id,
        user_id=normal_user.id,
        status=JobStatus.COMPLETED,
        progress_pct=100,
    )
    job2 = JobRun(
        job_type=JobType.GSC_SYNC,
        project_id=project.id,
        user_id=normal_user.id,
        status=JobStatus.RUNNING,
        progress_pct=30,
    )
    db.add(job1)
    db.add(job2)
    db.commit()

    # List project jobs
    response = client.get(
        f"{settings.API_V1_STR}/jobs/project/{project.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert content["count"] >= 2
    assert isinstance(content["data"], list)


def test_list_project_jobs_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test listing jobs for a non-existent project."""
    response = client.get(
        f"{settings.API_V1_STR}/jobs/project/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Project not found"


def test_cancel_job(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test canceling a running job."""
    # Create a project
    project = create_random_project(db, owner_id=normal_user.id)

    # Create a running job
    from app.models.job import JobRun, JobStatus, JobType

    job = JobRun(
        job_type=JobType.AUDIT,
        project_id=project.id,
        user_id=normal_user.id,
        status=JobStatus.RUNNING,
        progress_pct=40,
        celery_task_id="test-task-456",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Cancel the job
    response = client.post(
        f"{settings.API_V1_STR}/jobs/{job.id}/cancel",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Job cancelled successfully"

    # Verify job is cancelled
    response = client.get(
        f"{settings.API_V1_STR}/jobs/{job.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["status"] == "cancelled"


def test_cancel_job_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test canceling a non-existent job."""
    response = client.post(
        f"{settings.API_V1_STR}/jobs/{uuid.uuid4()}/cancel",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Job not found"


def test_cancel_already_completed_job(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test canceling an already completed job should fail."""
    # Create a project
    project = create_random_project(db, owner_id=normal_user.id)

    # Create a completed job
    from app.models.job import JobRun, JobStatus, JobType

    job = JobRun(
        job_type=JobType.AUDIT,
        project_id=project.id,
        user_id=normal_user.id,
        status=JobStatus.COMPLETED,
        progress_pct=100,
        finished_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Try to cancel the job
    response = client.post(
        f"{settings.API_V1_STR}/jobs/{job.id}/cancel",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 400
    content = response.json()
    assert "Cannot cancel" in content["detail"]


def test_job_authorization(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test that users can only access their own jobs."""
    # Create a job for a different user
    from app.models.job import JobRun, JobStatus, JobType
    from tests.utils.user import create_random_user

    other_user = create_random_user(db)
    project = create_random_project(db, owner_id=other_user.id)

    job = JobRun(
        job_type=JobType.AUDIT,
        project_id=project.id,
        user_id=other_user.id,
        status=JobStatus.RUNNING,
        progress_pct=25,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Try to access the job with a different user
    response = client.get(
        f"{settings.API_V1_STR}/jobs/{job.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 400
    content = response.json()
    assert content["detail"] == "Not enough permissions"
