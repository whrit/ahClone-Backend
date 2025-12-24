"""
Links (Backlinks) tracking models for Sprint 4.

Database tables:
- link_snapshots: CommonCrawl ingestion snapshots
- backlink_edges: Individual backlink records
- ref_domain_agg: Referring domain aggregations
- anchor_agg: Anchor text aggregations
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Index
from sqlmodel import Field, SQLModel

# ==================== Database Table Models ====================


class LinkSnapshot(SQLModel, table=True):
    """
    Tracks CommonCrawl data ingestion snapshots.

    Each snapshot represents a crawl from CommonCrawl (e.g., CC-MAIN-2024-10)
    and tracks the ingestion status, counts, and duration.
    """

    __tablename__ = "link_snapshots"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source: str = Field(default="commoncrawl")
    crawl_id: str  # e.g., "CC-MAIN-2024-10"
    subset_spec: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    status: str = Field(default="pending")  # pending/ingesting/completed/failed
    error_message: str | None = Field(default=None)
    edges_count: int = Field(default=0)
    domains_count: int = Field(default=0)
    duration_seconds: int | None = Field(default=None)


class BacklinkEdge(SQLModel, table=True):
    """
    Individual backlink records from CommonCrawl.

    Stores the raw link data including source/target URLs, domains,
    anchor text, and link attributes (nofollow, sponsored, UGC).
    """

    __tablename__ = "backlink_edges"
    __table_args__ = (
        Index("ix_backlink_target_domain", "target_domain"),
        Index("ix_backlink_source_domain", "source_domain"),
        Index("ix_backlink_snapshot", "snapshot_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    snapshot_id: uuid.UUID = Field(
        foreign_key="link_snapshots.id", nullable=False, ondelete="CASCADE"
    )
    source_url: str
    target_url: str
    source_domain: str = Field(index=True)
    target_domain: str = Field(index=True)
    anchor_text: str | None = Field(default=None)
    is_nofollow: bool = Field(default=False)
    is_sponsored: bool = Field(default=False)
    is_ugc: bool = Field(default=False)
    first_seen: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_seen: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class RefDomainAgg(SQLModel, table=True):
    """
    Aggregated referring domain statistics.

    Pre-aggregates backlink counts per referring domain to target domain pair,
    tracking dofollow/nofollow splits and top anchor texts.
    """

    __tablename__ = "ref_domain_agg"
    __table_args__ = (
        Index("ix_ref_domain_target", "target_domain"),
        Index("ix_ref_domain_ref", "ref_domain"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    snapshot_id: uuid.UUID = Field(
        foreign_key="link_snapshots.id", nullable=False, ondelete="CASCADE"
    )
    target_domain: str = Field(index=True)
    ref_domain: str = Field(index=True)
    backlinks_count: int = Field(default=1)
    dofollow_count: int = Field(default=0)
    nofollow_count: int = Field(default=0)
    first_seen: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_seen: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    top_anchors: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class AnchorAgg(SQLModel, table=True):
    """
    Aggregated anchor text statistics.

    Pre-aggregates backlink and referring domain counts per anchor text
    for a given target domain.
    """

    __tablename__ = "anchor_agg"
    __table_args__ = (Index("ix_anchor_target_domain", "target_domain"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    snapshot_id: uuid.UUID = Field(
        foreign_key="link_snapshots.id", nullable=False, ondelete="CASCADE"
    )
    target_domain: str = Field(index=True)
    anchor_text: str
    backlinks_count: int = Field(default=1)
    ref_domains_count: int = Field(default=1)


# ==================== API Response Models ====================


class RefDomainRow(SQLModel):
    """API response row for referring domains list."""

    ref_domain: str
    backlinks: int
    dofollow: int
    nofollow: int
    first_seen: datetime
    last_seen: datetime


class RefDomainsResponse(SQLModel):
    """API response for referring domains endpoint."""

    data: list[RefDomainRow]
    total: int


class BacklinkRow(SQLModel):
    """API response row for backlinks list."""

    source_url: str
    target_url: str
    source_domain: str
    anchor_text: str | None
    is_nofollow: bool
    first_seen: datetime
    last_seen: datetime


class BacklinksResponse(SQLModel):
    """API response for backlinks endpoint."""

    data: list[BacklinkRow]
    total: int


class AnchorRow(SQLModel):
    """API response row for anchor texts list."""

    anchor_text: str
    backlinks: int
    ref_domains: int


class AnchorsResponse(SQLModel):
    """API response for anchor texts endpoint."""

    data: list[AnchorRow]
    total: int


class NewLostLink(SQLModel):
    """API response row for new/lost backlinks."""

    source_url: str
    target_url: str
    source_domain: str
    anchor_text: str | None
    is_nofollow: bool
    date: datetime


class NewLostResponse(SQLModel):
    """API response for new/lost backlinks endpoint."""

    data: list[NewLostLink]
    total: int


class OverlapDomain(SQLModel):
    """API response row for backlink overlap analysis."""

    domain: str
    links_to_a: int
    links_to_b: int
    total_backlinks: int


class OverlapResponse(SQLModel):
    """API response for backlink overlap endpoint."""

    data: list[OverlapDomain]
    total: int


class IntersectDomain(SQLModel):
    """API response row for backlink intersection analysis."""

    domain: str
    backlinks_count: int
    dofollow_count: int
    nofollow_count: int


class IntersectResponse(SQLModel):
    """API response for backlink intersection endpoint."""

    data: list[IntersectDomain]
    total: int
