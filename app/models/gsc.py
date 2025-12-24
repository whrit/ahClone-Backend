"""
GSC (Google Search Console) models.

Database tables:
- gsc_properties: GSC property configuration per project
- gsc_query_daily: Daily query performance metrics
- gsc_page_daily: Daily page performance metrics
- keyword_clusters: Keyword groupings
- keyword_cluster_members: Keywords within clusters
"""

import uuid
from datetime import datetime, timezone
from datetime import date as date_type
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.project import Project


# ==================== Database Table Models ====================


class GSCProperty(SQLModel, table=True):
    """
    GSC property configuration for a project.

    Stores the Google Search Console property information and sync status.
    One-to-one relationship with Project.
    """
    __tablename__ = "gsc_properties"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        unique=True,
        index=True,
        ondelete="CASCADE"
    )
    site_url: str = Field(max_length=512)  # e.g., "sc-domain:example.com"
    permission_level: str | None = Field(default=None, max_length=50)
    verified: bool = Field(default=False)
    linked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_sync_at: datetime | None = Field(default=None)
    sync_status: str = Field(default="pending", max_length=50)
    sync_error: str | None = Field(default=None, max_length=2000)
    search_type: str = Field(default="web", max_length=50)

    # Relationships
    project: "Project" = Relationship(back_populates="gsc_property")


class GSCQueryDaily(SQLModel, table=True):
    """
    Daily query performance metrics from GSC.

    Stores performance data for search queries on a daily basis.
    """
    __tablename__ = "gsc_query_daily"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    date: date_type = Field(index=True)
    query: str = Field(max_length=1000, index=True)
    page: str | None = Field(default=None, max_length=2048)
    country: str | None = Field(default=None, max_length=10)
    device: str | None = Field(default=None, max_length=20)

    # Metrics
    clicks: int = Field(default=0)
    impressions: int = Field(default=0)
    ctr: float = Field(default=0.0)
    position: float = Field(default=0.0)


class GSCPageDaily(SQLModel, table=True):
    """
    Daily page performance metrics from GSC.

    Stores performance data for pages on a daily basis.
    """
    __tablename__ = "gsc_page_daily"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    date: date_type = Field(index=True)
    page: str = Field(max_length=2048)
    country: str | None = Field(default=None, max_length=10)
    device: str | None = Field(default=None, max_length=20)

    # Metrics
    clicks: int = Field(default=0)
    impressions: int = Field(default=0)
    ctr: float = Field(default=0.0)
    position: float = Field(default=0.0)


class KeywordCluster(SQLModel, table=True):
    """
    Keyword clusters for grouping related queries.

    Groups similar queries together for analysis and reporting.
    """
    __tablename__ = "keyword_clusters"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    label: str = Field(max_length=255)
    algorithm: str = Field(max_length=50)  # e.g., "kmeans", "hierarchical"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Aggregated metrics
    total_clicks: int = Field(default=0)
    total_impressions: int = Field(default=0)
    avg_position: float = Field(default=0.0)
    query_count: int = Field(default=0)

    # Relationships
    members: list["KeywordClusterMember"] = Relationship(
        back_populates="cluster",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class KeywordClusterMember(SQLModel, table=True):
    """
    Individual keywords within a cluster.

    Links queries to their parent cluster with a weight/similarity score.
    """
    __tablename__ = "keyword_cluster_members"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    cluster_id: uuid.UUID = Field(
        foreign_key="keyword_clusters.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    query: str = Field(max_length=1000)
    weight: float = Field(default=0.0)  # Similarity/cluster weight

    # Relationships
    cluster: KeywordCluster = Relationship(back_populates="members")


# ==================== API Response Models ====================


class GSCPropertyPublic(SQLModel):
    """Public schema for returning GSC property data."""
    id: uuid.UUID
    project_id: uuid.UUID
    site_url: str
    permission_level: str | None
    verified: bool
    linked_at: datetime
    last_sync_at: datetime | None
    sync_status: str
    sync_error: str | None
    search_type: str


class GSCQueryRow(SQLModel):
    """Schema for a single query row in GSC API responses."""
    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float


class GSCQueriesResponse(SQLModel):
    """Schema for returning multiple GSC queries."""
    data: list[GSCQueryRow]
    count: int


class GSCPageRow(SQLModel):
    """Schema for a single page row in GSC API responses."""
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float


class GSCPagesResponse(SQLModel):
    """Schema for returning multiple GSC pages."""
    data: list[GSCPageRow]
    count: int


class OpportunityRow(SQLModel):
    """Schema for SEO opportunity data."""
    query: str
    impressions: int
    clicks: int
    ctr: float
    position: float
    opportunity_type: str  # e.g., "high_impressions_low_ctr", "position_8_15"
    potential_clicks: int


class OpportunitiesResponse(SQLModel):
    """Schema for returning multiple opportunities."""
    data: list[OpportunityRow]
    count: int


class ClusterPublic(SQLModel):
    """Public schema for returning keyword cluster data."""
    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    algorithm: str
    created_at: datetime
    total_clicks: int
    total_impressions: int
    avg_position: float
    query_count: int
