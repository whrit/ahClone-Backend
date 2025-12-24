"""API routes for audit operations."""
import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import desc, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.rate_limit import limiter, strict_limit
from app.core.exceptions import NotFoundError, AuthorizationError
from app.models import Project, User
from app.models.audit import (
    AuditIssue,
    AuditIssuesPublic,
    AuditRun,
    AuditRunPublic,
    AuditRunsPublic,
    AuditStatus,
    CrawledPage,
    CrawledPagePublic,
    CrawledPagesPublic,
    IssueSeverity,
    IssueType,
)
from app.models.project import ProjectSettings
from app.tasks.audit import run_audit

router = APIRouter(tags=["audits"])


def get_project_or_404(
    session: SessionDep, project_id: uuid.UUID, current_user: User
) -> Project:
    """
    Get project by ID, check ownership, and raise appropriate exceptions.

    Args:
        session: Database session
        project_id: Project UUID
        current_user: Current authenticated user

    Returns:
        Project instance

    Raises:
        NotFoundError: If project not found
        AuthorizationError: If user doesn't have permission
    """
    project = session.get(Project, project_id)
    if not project:
        raise NotFoundError("Project", str(project_id))
    if not current_user.is_superuser and (project.created_by_id != current_user.id):
        raise AuthorizationError("access this project")
    return project


@router.post("/projects/{project_id}/audits/", response_model=AuditRunPublic)
@limiter.limit(strict_limit())
def start_audit(
    request: Request,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> Any:
    """
    Create new audit run and queue it for execution.

    Creates a new AuditRun with a config snapshot from the project settings,
    then queues the run_audit Celery task.
    """
    project = get_project_or_404(session, project_id, current_user)

    # Create config snapshot from project settings
    settings = ProjectSettings(**project.settings)
    config = {
        "max_pages": settings.max_pages,
        "max_depth": settings.max_depth,
        "crawl_concurrency": settings.crawl_concurrency,
        "user_agent": settings.user_agent,
        "respect_robots_txt": settings.respect_robots_txt,
        "include_subdomains": settings.include_subdomains,
        "strip_query_params": settings.strip_query_params,
        "include_patterns": settings.include_patterns,
        "exclude_patterns": settings.exclude_patterns,
        "enable_js_rendering": settings.enable_js_rendering,
        "js_render_mode": settings.js_render_mode,
        "max_render_pages": settings.max_render_pages,
        "render_timeout_ms": settings.render_timeout_ms,
    }

    # Create audit run
    audit_run = AuditRun(
        project_id=project_id,
        status=AuditStatus.QUEUED,
        config=config,
        progress_pct=0.0,
    )
    session.add(audit_run)
    session.commit()
    session.refresh(audit_run)

    # Queue Celery task
    run_audit.delay(str(project_id), str(audit_run.id))

    return audit_run


@router.get("/projects/{project_id}/audits/", response_model=AuditRunsPublic)
def list_audits(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    List all audit runs for a project with pagination.

    Results are ordered by created_at descending (newest first).
    """
    _ = get_project_or_404(session, project_id, current_user)

    # Count total audit runs
    count_statement = (
        select(func.count())
        .select_from(AuditRun)
        .where(AuditRun.project_id == project_id)
    )
    count = session.exec(count_statement).one()

    # Get audit runs with pagination
    statement = (
        select(AuditRun)
        .where(AuditRun.project_id == project_id)
        .order_by(desc(AuditRun.created_at))
        .offset(skip)
        .limit(limit)
    )
    audit_runs = session.exec(statement).all()

    return AuditRunsPublic(data=audit_runs, count=count)


@router.get("/projects/{project_id}/audits/{audit_id}", response_model=AuditRunPublic)
def get_audit(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
) -> Any:
    """Get a single audit run by ID."""
    _ = get_project_or_404(session, project_id, current_user)

    audit_run = session.get(AuditRun, audit_id)
    if not audit_run or audit_run.project_id != project_id:
        raise NotFoundError("Audit run", str(audit_id))

    return audit_run


@router.get(
    "/projects/{project_id}/audits/{audit_id}/issues", response_model=AuditIssuesPublic
)
def get_audit_issues(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    severity: IssueSeverity | None = None,
    issue_type: IssueType | None = None,
    is_new: bool | None = None,
) -> Any:
    """
    Get issues for an audit run with optional filters.

    Supports filtering by severity, issue_type, and is_new.
    Includes pagination with skip/limit.
    """
    _ = get_project_or_404(session, project_id, current_user)

    # Verify audit run exists and belongs to project
    audit_run = session.get(AuditRun, audit_id)
    if not audit_run or audit_run.project_id != project_id:
        raise NotFoundError("Audit run", str(audit_id))

    # Build base query
    statement = select(AuditIssue).where(AuditIssue.audit_run_id == audit_id)

    # Apply filters
    if severity is not None:
        statement = statement.where(AuditIssue.severity == severity)
    if issue_type is not None:
        statement = statement.where(AuditIssue.issue_type == issue_type)
    if is_new is not None:
        statement = statement.where(AuditIssue.is_new == is_new)

    # Count total
    count_statement = select(func.count()).select_from(statement.subquery())
    count = session.exec(count_statement).one()

    # Get paginated results
    statement = statement.offset(skip).limit(limit)
    issues = session.exec(statement).all()

    return AuditIssuesPublic(data=issues, count=count)


@router.get(
    "/projects/{project_id}/audits/{audit_id}/pages", response_model=CrawledPagesPublic
)
def get_audit_pages(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    status_code: int | None = None,
    is_rendered: bool | None = None,
) -> Any:
    """
    Get crawled pages for an audit run with optional filters.

    Supports filtering by status_code and is_rendered.
    Includes pagination with skip/limit.
    """
    _ = get_project_or_404(session, project_id, current_user)

    # Verify audit run exists and belongs to project
    audit_run = session.get(AuditRun, audit_id)
    if not audit_run or audit_run.project_id != project_id:
        raise NotFoundError("Audit run", str(audit_id))

    # Build base query
    statement = select(CrawledPage).where(CrawledPage.audit_run_id == audit_id)

    # Apply filters
    if status_code is not None:
        statement = statement.where(CrawledPage.status_code == status_code)
    if is_rendered is not None:
        statement = statement.where(CrawledPage.is_rendered == is_rendered)

    # Count total
    count_statement = select(func.count()).select_from(statement.subquery())
    count = session.exec(count_statement).one()

    # Get paginated results
    statement = statement.offset(skip).limit(limit)
    pages = session.exec(statement).all()

    return CrawledPagesPublic(data=pages, count=count)


@router.get(
    "/projects/{project_id}/audits/{audit_id}/pages/{page_id}",
    response_model=CrawledPagePublic,
)
def get_page_detail(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
    page_id: uuid.UUID,
) -> Any:
    """Get a single crawled page by ID."""
    _ = get_project_or_404(session, project_id, current_user)

    # Verify audit run exists and belongs to project
    audit_run = session.get(AuditRun, audit_id)
    if not audit_run or audit_run.project_id != project_id:
        raise NotFoundError("Audit run", str(audit_id))

    # Get page
    page = session.get(CrawledPage, page_id)
    if not page or page.audit_run_id != audit_id:
        raise NotFoundError("Page", str(page_id))

    return page


@router.get("/projects/{project_id}/audits/{audit_id}/export/issues.csv")
def export_issues_csv(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
    severity: IssueSeverity | None = None,
    issue_type: IssueType | None = None,
    is_new: bool | None = None,
) -> StreamingResponse:
    """
    Export audit issues as CSV file.

    Supports the same filters as get_audit_issues endpoint.
    Returns a streaming CSV response.
    """
    _ = get_project_or_404(session, project_id, current_user)

    # Verify audit run exists and belongs to project
    audit_run = session.get(AuditRun, audit_id)
    if not audit_run or audit_run.project_id != project_id:
        raise NotFoundError("Audit run", str(audit_id))

    # Build query with same filters as get_audit_issues
    statement = select(AuditIssue).where(AuditIssue.audit_run_id == audit_id)

    if severity is not None:
        statement = statement.where(AuditIssue.severity == severity)
    if issue_type is not None:
        statement = statement.where(AuditIssue.issue_type == issue_type)
    if is_new is not None:
        statement = statement.where(AuditIssue.is_new == is_new)

    issues = session.exec(statement).all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "id",
            "audit_run_id",
            "page_url",
            "issue_type",
            "severity",
            "is_new",
            "details",
        ]
    )

    # Write data rows
    for issue in issues:
        writer.writerow(
            [
                str(issue.id),
                str(issue.audit_run_id),
                issue.page_url,
                issue.issue_type,
                issue.severity,
                issue.is_new,
                str(issue.details),
            ]
        )

    # Prepare streaming response
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_{audit_id}_issues.csv"
        },
    )
