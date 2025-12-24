import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.project import Project


class AuditStatus(str, Enum):
    QUEUED = "queued"
    CRAWLING = "crawling"
    RENDERING = "rendering"
    ANALYZING = "analyzing"
    DIFFING = "diffing"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueType(str, Enum):
    # Critical
    SERVER_ERROR_5XX = "server_error_5xx"
    REDIRECT_LOOP = "redirect_loop"
    REDIRECT_CHAIN = "redirect_chain"
    BROKEN_INTERNAL_LINK = "broken_internal_link"

    # High
    CLIENT_ERROR_4XX = "client_error_4xx"
    MISSING_TITLE = "missing_title"
    DUPLICATE_TITLE = "duplicate_title"
    MISSING_META_DESCRIPTION = "missing_meta_description"

    # Medium
    TITLE_TOO_LONG = "title_too_long"
    TITLE_TOO_SHORT = "title_too_short"
    META_DESC_TOO_LONG = "meta_desc_too_long"
    META_DESC_TOO_SHORT = "meta_desc_too_short"
    MISSING_H1 = "missing_h1"
    MULTIPLE_H1 = "multiple_h1"
    MISSING_CANONICAL = "missing_canonical"
    CANONICAL_MISMATCH = "canonical_mismatch"
    NON_HTTPS = "non_https"

    # Low
    THIN_CONTENT = "thin_content"
    ORPHAN_PAGE = "orphan_page"


# Issue type to severity mapping
ISSUE_SEVERITY_MAP: dict[IssueType, IssueSeverity] = {
    IssueType.SERVER_ERROR_5XX: IssueSeverity.CRITICAL,
    IssueType.REDIRECT_LOOP: IssueSeverity.CRITICAL,
    IssueType.BROKEN_INTERNAL_LINK: IssueSeverity.CRITICAL,
    IssueType.REDIRECT_CHAIN: IssueSeverity.HIGH,
    IssueType.CLIENT_ERROR_4XX: IssueSeverity.HIGH,
    IssueType.MISSING_TITLE: IssueSeverity.HIGH,
    IssueType.DUPLICATE_TITLE: IssueSeverity.HIGH,
    IssueType.NON_HTTPS: IssueSeverity.HIGH,
    IssueType.MISSING_META_DESCRIPTION: IssueSeverity.MEDIUM,
    IssueType.MISSING_H1: IssueSeverity.MEDIUM,
    IssueType.MULTIPLE_H1: IssueSeverity.MEDIUM,
    IssueType.MISSING_CANONICAL: IssueSeverity.MEDIUM,
    IssueType.CANONICAL_MISMATCH: IssueSeverity.MEDIUM,
    IssueType.THIN_CONTENT: IssueSeverity.MEDIUM,
    IssueType.ORPHAN_PAGE: IssueSeverity.MEDIUM,
    IssueType.TITLE_TOO_LONG: IssueSeverity.LOW,
    IssueType.TITLE_TOO_SHORT: IssueSeverity.LOW,
    IssueType.META_DESC_TOO_LONG: IssueSeverity.LOW,
    IssueType.META_DESC_TOO_SHORT: IssueSeverity.LOW,
}


class AuditRunConfig(SQLModel):
    """Snapshot of crawl config at run time"""
    max_pages: int = 1000
    max_depth: int = 10
    crawl_concurrency: int = 5
    user_agent: str = "SEOPlatformBot/1.0"
    respect_robots_txt: bool = True
    include_subdomains: bool = False
    strip_query_params: bool = False
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    enable_js_rendering: bool = False
    js_render_mode: str = "hybrid"
    max_render_pages: int = 100
    render_timeout_ms: int = 30000


class AuditRunStats(SQLModel):
    """Aggregated stats for the audit run"""
    total_pages: int = 0
    pages_ok: int = 0
    pages_redirect: int = 0
    pages_error: int = 0
    total_issues: int = 0
    issues_critical: int = 0
    issues_high: int = 0
    issues_medium: int = 0
    issues_low: int = 0


class AuditRun(SQLModel, table=True):
    __tablename__ = "audit_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="projects.id", nullable=False, ondelete="CASCADE")
    status: AuditStatus = Field(default=AuditStatus.QUEUED)
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    stats: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None, max_length=2000)

    # Progress tracking
    progress_pct: float = Field(default=0.0)
    progress_message: str | None = Field(default=None, max_length=500)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    project: "Project" = Relationship(back_populates="audit_runs")
    pages: list["CrawledPage"] = Relationship(
        back_populates="audit_run",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    issues: list["AuditIssue"] = Relationship(
        back_populates="audit_run",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "[AuditIssue.audit_run_id]"
        },
    )
    link_edges: list["AuditLinkEdge"] = Relationship(
        back_populates="audit_run",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class CrawledPage(SQLModel, table=True):
    __tablename__ = "crawled_pages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    audit_run_id: uuid.UUID = Field(foreign_key="audit_runs.id", nullable=False, ondelete="CASCADE")

    # URL info
    url: str = Field(max_length=2048, index=True)
    final_url: str = Field(max_length=2048)  # After redirects
    depth: int = Field(ge=0)

    # Response info
    status_code: int
    content_type: str | None = Field(default=None, max_length=100)
    response_time_ms: int | None = Field(default=None)

    # Redirect chain
    redirect_chain: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Extracted data
    title: str | None = Field(default=None, max_length=1000)
    meta_description: str | None = Field(default=None, max_length=2000)
    canonical: str | None = Field(default=None, max_length=2048)
    h1_count: int | None = Field(default=None)
    first_h1: str | None = Field(default=None, max_length=1000)
    word_count: int | None = Field(default=None)
    meta_robots: str | None = Field(default=None, max_length=200)

    # Rendering info
    is_rendered: bool = Field(default=False)
    rendered_at: datetime | None = Field(default=None)
    rendered_title: str | None = Field(default=None, max_length=1000)
    rendered_meta_description: str | None = Field(default=None, max_length=2000)
    rendered_h1_count: int | None = Field(default=None)
    rendered_word_count: int | None = Field(default=None)
    content_hash: str | None = Field(default=None, max_length=64)

    # Timestamps
    crawled_at: datetime

    # Relationships
    audit_run: "AuditRun" = Relationship(back_populates="pages")


class AuditIssue(SQLModel, table=True):
    __tablename__ = "audit_issues"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    audit_run_id: uuid.UUID = Field(foreign_key="audit_runs.id", nullable=False, ondelete="CASCADE")
    page_url: str = Field(max_length=2048, index=True)

    issue_type: IssueType
    severity: IssueSeverity
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # For diff tracking
    first_seen_run_id: uuid.UUID | None = Field(default=None, foreign_key="audit_runs.id")
    is_new: bool = Field(default=True)  # New in this run vs previous

    # Relationships
    audit_run: "AuditRun" = Relationship(
        back_populates="issues",
        sa_relationship_kwargs={"foreign_keys": "[AuditIssue.audit_run_id]"}
    )


class AuditLinkEdge(SQLModel, table=True):
    __tablename__ = "audit_link_edges"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    audit_run_id: uuid.UUID = Field(foreign_key="audit_runs.id", nullable=False, ondelete="CASCADE")

    source_url: str = Field(max_length=2048, index=True)
    target_url: str = Field(max_length=2048, index=True)
    anchor_text: str | None = Field(default=None, max_length=1000)
    is_internal: bool = Field(default=True)
    is_followed: bool = Field(default=True)  # rel=nofollow check
    target_status_code: int | None = Field(default=None)

    # Relationships
    audit_run: "AuditRun" = Relationship(back_populates="link_edges")


# API Response Models
class AuditRunPublic(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: AuditStatus
    config: dict[str, Any]
    stats: dict[str, Any] | None
    progress_pct: float
    progress_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class AuditRunsPublic(SQLModel):
    data: list[AuditRunPublic]
    count: int


class CrawledPagePublic(SQLModel):
    id: uuid.UUID
    audit_run_id: uuid.UUID
    url: str
    final_url: str
    depth: int
    status_code: int
    content_type: str | None
    response_time_ms: int | None
    redirect_chain: list[dict[str, Any]] | None
    title: str | None
    meta_description: str | None
    canonical: str | None
    h1_count: int | None
    first_h1: str | None
    word_count: int | None
    meta_robots: str | None
    is_rendered: bool
    rendered_at: datetime | None
    rendered_title: str | None
    rendered_meta_description: str | None
    rendered_h1_count: int | None
    rendered_word_count: int | None
    content_hash: str | None
    crawled_at: datetime


class CrawledPagesPublic(SQLModel):
    data: list[CrawledPagePublic]
    count: int


class AuditIssuePublic(SQLModel):
    id: uuid.UUID
    audit_run_id: uuid.UUID
    page_url: str
    issue_type: IssueType
    severity: IssueSeverity
    details: dict[str, Any]
    first_seen_run_id: uuid.UUID | None
    is_new: bool


class AuditIssuesPublic(SQLModel):
    data: list[AuditIssuePublic]
    count: int
