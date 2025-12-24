"""
SERP (Search Engine Results Page) tracking models.

Database tables:
- keyword_targets: Keywords to track rankings for
- rank_observations: Individual rank position observations
- serp_snapshots: Full SERP snapshots with results
"""


import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.project import Project


# ==================== Enums ====================


class DeviceType(str, Enum):
    """Device types for SERP tracking."""
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


class SearchEngine(str, Enum):
    """Supported search engines."""
    GOOGLE = "google"
    BING = "bing"


class RefreshStatus(str, Enum):
    """Status of SERP refresh operation."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


class ObservationStatus(str, Enum):
    """Status of rank observation."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class RefreshFrequency(str, Enum):
    """Common refresh frequency options."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


# ==================== Database Table Models ====================


class KeywordTarget(SQLModel, table=True):
    """
    Keywords to track for SERP position monitoring.

    Stores keyword configuration including locale, device type, search engine,
    and refresh schedule. Caches latest position and position change for quick access.
    """
    __tablename__ = "keyword_targets"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    keyword: str = Field(max_length=500)
    locale: str = Field(max_length=10)  # e.g., "en-US", "en-GB"
    device: DeviceType = Field(default=DeviceType.DESKTOP)
    search_engine: SearchEngine = Field(default=SearchEngine.GOOGLE)
    provider_key: str = Field(default="serpapi", max_length=50)  # "serpapi", "valueserp", etc.
    refresh_frequency_hours: int = Field(default=24)
    is_active: bool = Field(default=True)

    # Cached latest metrics for quick access
    latest_position: int | None = Field(default=None)
    position_change: int | None = Field(default=None)  # Change from previous observation

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_refresh_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_refresh_status: str | None = Field(default=None, max_length=50)

    # Relationships
    observations: list["RankObservation"] = Relationship(
        back_populates="keyword_target",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    snapshots: list["SerpSnapshot"] = Relationship(
        back_populates="keyword_target",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class RankObservation(SQLModel, table=True):
    """
    Single position observation for a keyword at a specific point in time.

    Records where a URL ranked for a tracked keyword including metadata
    like title, snippet, and domain.
    """
    __tablename__ = "rank_observations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    keyword_target_id: uuid.UUID = Field(
        foreign_key="keyword_targets.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    observed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )  # When this observation was captured
    rank: int  # Position in SERP (1-based)
    url: str | None = Field(default=None, max_length=2048)
    domain: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    snippet: str | None = Field(default=None, max_length=1000)
    status: RefreshStatus = Field(default=RefreshStatus.PENDING)

    # Relationships
    keyword_target: KeywordTarget = Relationship(back_populates="observations")


class SerpSnapshot(SQLModel, table=True):
    """
    Complete SERP snapshot with all organic results.

    Stores the full set of organic search results as JSON for historical analysis
    and comparison.
    """
    __tablename__ = "serp_snapshots"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    keyword_target_id: uuid.UUID = Field(
        foreign_key="keyword_targets.id",
        nullable=False,
        index=True,
        ondelete="CASCADE"
    )
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    results_json: dict[str, Any] = Field(sa_column=Column(JSON))  # Full organic results
    total_results: int | None = Field(default=None)  # Total number of results found
    raw_response: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # Raw API response

    # Relationships
    keyword_target: KeywordTarget = Relationship(back_populates="snapshots")


# ==================== API Request Models ====================


class KeywordTargetCreate(SQLModel):
    """Schema for creating a new keyword target."""
    keyword: str = Field(max_length=500)
    locale: str = Field(max_length=10)
    device: DeviceType = DeviceType.DESKTOP
    search_engine: SearchEngine = SearchEngine.GOOGLE
    provider_key: str = Field(default="serpapi", max_length=50)
    refresh_frequency_hours: int = Field(default=24, ge=1, le=168)  # 1 hour to 1 week


# ==================== API Response Models ====================


class KeywordTargetPublic(SQLModel):
    """Public schema for returning keyword target data."""
    id: uuid.UUID
    project_id: uuid.UUID
    keyword: str
    locale: str
    device: DeviceType
    search_engine: SearchEngine
    provider_key: str
    refresh_frequency_hours: int
    is_active: bool
    latest_position: int | None
    position_change: int | None
    created_at: datetime
    updated_at: datetime
    last_refresh_at: datetime | None
    last_refresh_status: str | None


class KeywordTargetsPublic(SQLModel):
    """Schema for returning multiple keyword targets."""
    data: list[KeywordTargetPublic]
    count: int


class RankObservationPublic(SQLModel):
    """Public schema for returning rank observation data."""
    id: uuid.UUID
    keyword_target_id: uuid.UUID
    observed_at: datetime
    rank: int
    url: str | None
    domain: str | None
    title: str | None
    snippet: str | None
    status: RefreshStatus


class RankObservationsPublic(SQLModel):
    """Schema for returning multiple rank observations."""
    data: list[RankObservationPublic]
    count: int


class RankHistoryResponse(SQLModel):
    """Schema for returning rank history."""
    data: list[RankObservationPublic]
    count: int


class SerpResultPublic(SQLModel):
    """Schema for a single SERP result."""
    position: int
    url: str
    domain: str
    title: str
    snippet: str
    displayed_url: str | None = None


class SerpSnapshotPublic(SQLModel):
    """Public schema for returning SERP snapshot data."""
    id: uuid.UUID
    keyword_target_id: uuid.UUID
    captured_at: datetime
    results: list[SerpResultPublic]
    total_results: int | None
