"""Tests for audit API routes."""
import uuid
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from app.models.audit import (
    AuditIssue,
    AuditRun,
    AuditStatus,
    CrawledPage,
    IssueSeverity,
    IssueType,
)
from app.models.project import ProjectSettings
from tests.utils.project import create_random_project


def test_start_audit(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test starting a new audit run."""
    project = create_random_project(db, owner_id=normal_user.id)

    with patch("app.api.routes.audits.run_audit") as mock_run_audit:
        mock_run_audit.delay = MagicMock()
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/audits/",
            headers=normal_user_token_headers,
        )
    assert response.status_code == 200
    content = response.json()
    assert content["project_id"] == str(project.id)
    assert content["status"] == AuditStatus.QUEUED
    assert "config" in content
    assert content["config"]["max_pages"] == project.settings["max_pages"]
    assert "id" in content
    assert content["progress_pct"] == 0.0
    # Verify Celery task was called
    mock_run_audit.delay.assert_called_once()


def test_start_audit_project_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test starting audit for non-existent project returns 404."""
    response = client.post(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}/audits/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_start_audit_unauthorized(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Test that users cannot start audits for projects they don't own."""
    # Create project owned by a different user
    project = create_random_project(db)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/",
        headers=normal_user_token_headers,
    )
    assert response.status_code in [400, 403, 404]


def test_list_audits(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing audit runs with pagination."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create multiple audit runs
    for _ in range(3):
        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.COMPLETED,
            config=ProjectSettings().model_dump(),
            stats={},
        )
        db.add(audit_run)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert content["count"] >= 3
    assert isinstance(content["data"], list)


def test_list_audits_pagination(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test audit listing pagination works correctly."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create 5 audit runs
    for _ in range(5):
        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.COMPLETED,
            config=ProjectSettings().model_dump(),
        )
        db.add(audit_run)
    db.commit()

    # Test skip and limit
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/?skip=1&limit=2",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 2


def test_get_audit(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting a single audit run."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
        stats={},
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(audit_run.id)
    assert content["project_id"] == str(project.id)
    assert content["status"] == AuditStatus.COMPLETED


def test_get_audit_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting non-existent audit returns 404."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_get_audit_issues(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting audit issues."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create test issues
    issue1 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page1",
        issue_type=IssueType.MISSING_TITLE,
        severity=IssueSeverity.HIGH,
        details={},
        is_new=True,
    )
    issue2 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page2",
        issue_type=IssueType.BROKEN_INTERNAL_LINK,
        severity=IssueSeverity.CRITICAL,
        details={},
        is_new=False,
    )
    db.add(issue1)
    db.add(issue2)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/issues",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert len(content["data"]) >= 2


def test_get_audit_issues_with_filters(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test filtering audit issues by severity, type, and is_new."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create issues with different severities and types
    issue1 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page1",
        issue_type=IssueType.MISSING_TITLE,
        severity=IssueSeverity.HIGH,
        details={},
        is_new=True,
    )
    issue2 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page2",
        issue_type=IssueType.BROKEN_INTERNAL_LINK,
        severity=IssueSeverity.CRITICAL,
        details={},
        is_new=False,
    )
    db.add(issue1)
    db.add(issue2)
    db.commit()

    # Test severity filter
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/issues?severity=critical",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 1
    assert content["data"][0]["severity"] == IssueSeverity.CRITICAL

    # Test is_new filter
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/issues?is_new=true",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 1
    assert content["data"][0]["is_new"] is True


def test_get_audit_pages(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting crawled pages."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create test pages
    page1 = CrawledPage(
        audit_run_id=audit_run.id,
        url="https://example.com/page1",
        final_url="https://example.com/page1",
        depth=0,
        status_code=200,
        crawled_at=datetime.now(timezone.utc),
    )
    page2 = CrawledPage(
        audit_run_id=audit_run.id,
        url="https://example.com/page2",
        final_url="https://example.com/page2",
        depth=1,
        status_code=404,
        crawled_at=datetime.now(timezone.utc),
    )
    db.add(page1)
    db.add(page2)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/pages",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert len(content["data"]) >= 2


def test_get_audit_pages_with_filters(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test filtering crawled pages by status_code and is_rendered."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create pages with different status codes
    page1 = CrawledPage(
        audit_run_id=audit_run.id,
        url="https://example.com/page1",
        final_url="https://example.com/page1",
        depth=0,
        status_code=200,
        is_rendered=True,
        crawled_at=datetime.now(timezone.utc),
    )
    page2 = CrawledPage(
        audit_run_id=audit_run.id,
        url="https://example.com/page2",
        final_url="https://example.com/page2",
        depth=1,
        status_code=404,
        is_rendered=False,
        crawled_at=datetime.now(timezone.utc),
    )
    db.add(page1)
    db.add(page2)
    db.commit()

    # Test status_code filter
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/pages?status_code=404",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 1
    assert content["data"][0]["status_code"] == 404

    # Test is_rendered filter
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/pages?is_rendered=true",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 1
    assert content["data"][0]["is_rendered"] is True


def test_get_page_detail(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting single page detail."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    page = CrawledPage(
        audit_run_id=audit_run.id,
        url="https://example.com/page1",
        final_url="https://example.com/page1",
        depth=0,
        status_code=200,
        title="Test Page",
        crawled_at=datetime.now(timezone.utc),
    )
    db.add(page)
    db.commit()
    db.refresh(page)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/pages/{page.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(page.id)
    assert content["url"] == "https://example.com/page1"
    assert content["title"] == "Test Page"


def test_get_page_detail_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting non-existent page returns 404."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/pages/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_export_issues_csv(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test exporting issues as CSV."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create test issues
    issue = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page1",
        issue_type=IssueType.MISSING_TITLE,
        severity=IssueSeverity.HIGH,
        details={"message": "Title is missing"},
        is_new=True,
    )
    db.add(issue)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/export/issues.csv",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"

    # Verify CSV content
    csv_content = response.text
    assert "page_url" in csv_content
    assert "issue_type" in csv_content
    assert "severity" in csv_content
    assert "https://example.com/page1" in csv_content


def test_export_issues_csv_with_filters(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test exporting issues as CSV with filters."""
    project = create_random_project(db, owner_id=normal_user.id)
    audit_run = AuditRun(
        project_id=project.id,
        status=AuditStatus.COMPLETED,
        config=ProjectSettings().model_dump(),
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Create issues with different severities
    issue1 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page1",
        issue_type=IssueType.MISSING_TITLE,
        severity=IssueSeverity.HIGH,
        details={},
        is_new=True,
    )
    issue2 = AuditIssue(
        audit_run_id=audit_run.id,
        page_url="https://example.com/page2",
        issue_type=IssueType.BROKEN_INTERNAL_LINK,
        severity=IssueSeverity.CRITICAL,
        details={},
        is_new=False,
    )
    db.add(issue1)
    db.add(issue2)
    db.commit()

    # Export only critical issues
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/audits/{audit_run.id}/export/issues.csv?severity=critical",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    csv_content = response.text
    assert "https://example.com/page2" in csv_content
    # Should only have one data row (plus header)
    lines = csv_content.strip().split("\n")
    assert len(lines) == 2  # Header + 1 data row
