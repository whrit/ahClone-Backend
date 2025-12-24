
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import HttpUrl, field_validator
from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models import User
    from app.models.audit import AuditRun
    from app.models.gsc import GSCProperty
    from app.models.serp import KeywordTarget


# ProjectSettings - embedded settings (stored as JSON in the database)
class ProjectSettings(SQLModel):
    """Project configuration settings stored as JSON."""
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
    audit_frequency: str = "weekly"
    gsc_sync_frequency: str = "daily"
    serp_refresh_frequency: str = "daily"
    keep_audit_runs: int = 10
    keep_serp_days: int = 90


# Shared properties for Project
class ProjectBase(SQLModel):
    """Base model for Project with shared properties."""
    name: str = Field(max_length=255, index=True)
    seed_url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator('seed_url')
    @classmethod
    def validate_seed_url(cls, v: str) -> str:
        """Validate that seed_url is a valid HTTP/HTTPS URL."""
        # Use Pydantic's HttpUrl for validation
        HttpUrl(url=v)
        return v


# Properties to receive on project creation
class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""
    settings: ProjectSettings | None = None


# Properties to receive on project update
class ProjectUpdate(SQLModel):
    """Schema for updating an existing project."""
    name: str | None = Field(default=None, max_length=255)
    seed_url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=1000)
    settings: ProjectSettings | None = None

    @field_validator('seed_url')
    @classmethod
    def validate_seed_url(cls, v: str | None) -> str | None:
        """Validate that seed_url is a valid HTTP/HTTPS URL if provided."""
        if v is not None:
            HttpUrl(url=v)
        return v


# Database model, database table inferred from class name
class Project(ProjectBase, table=True):
    """Project database model."""
    __tablename__ = "projects"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    settings: dict[str, Any] = Field(default_factory=lambda: ProjectSettings().model_dump(), sa_column=Column(JSON))
    created_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_audit_at: datetime | None = Field(default=None)
    last_gsc_sync_at: datetime | None = Field(default=None)
    last_serp_refresh_at: datetime | None = Field(default=None)
    last_links_snapshot_at: datetime | None = Field(default=None)
    last_ppc_sync_at: datetime | None = Field(default=None)

    # Relationships
    created_by: "User" = Relationship(back_populates="projects")
    audit_runs: list["AuditRun"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    gsc_property: "GSCProperty" = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False}
    )
    # Note: keyword_targets relationship removed to avoid circular dependency
    # Access keyword targets via: session.exec(select(KeywordTarget).where(KeywordTarget.project_id == project.id))


# Properties to return via API, id is always required
class ProjectPublic(ProjectBase):
    """Public schema for returning project data."""
    id: uuid.UUID
    created_by_id: uuid.UUID
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_audit_at: datetime | None
    last_gsc_sync_at: datetime | None
    last_serp_refresh_at: datetime | None
    last_links_snapshot_at: datetime | None
    last_ppc_sync_at: datetime | None


class ProjectsPublic(SQLModel):
    """Schema for returning multiple projects."""
    data: list[ProjectPublic]
    count: int
