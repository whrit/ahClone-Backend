"""
Ads and Traffic tracking models for Sprint 5.

Database tables:
- ads_accounts: Google Ads account linkage
- ads_campaign_daily: Daily campaign performance metrics
- ads_keyword_daily: Daily keyword performance metrics
- transparency_creatives: Competitor ads from transparency datasets
- traffic_daily: Multi-source traffic data (GA4, GSC, CrUX, CSV)
"""

import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column, DateTime, Index
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.project import Project

# ==================== Database Table Models ====================


class AdsAccount(SQLModel, table=True):
    """
    Linked Google Ads account for a project.

    Stores Google Ads customer ID and sync status.
    One-to-one relationship with Project.
    """

    __tablename__ = "ads_accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        unique=True,
        index=True,
        ondelete="CASCADE",
    )
    customer_id: str = Field(max_length=50)  # Google Ads customer ID
    descriptive_name: str | None = Field(default=None, max_length=255)
    currency_code: str = Field(default="USD", max_length=10)
    linked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_sync_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    sync_status: str = Field(default="pending", max_length=50)

    # Relationships
    project: "Project" = Relationship(back_populates="ads_account")


class AdsCampaignDaily(SQLModel, table=True):
    """
    Daily campaign performance metrics from Google Ads.

    Stores aggregated campaign-level metrics on a daily basis.
    """

    __tablename__ = "ads_campaign_daily"
    __table_args__ = (Index("ix_ads_campaign_project_date", "project_id", "date"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    date: date_type = Field(index=True)
    campaign_id: str = Field(max_length=100)
    campaign_name: str = Field(max_length=255)
    campaign_status: str | None = Field(default=None, max_length=50)

    # Metrics
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    cost_micros: int = Field(default=0)  # Cost in micros (e.g., $1.00 = 1,000,000)
    conversions: float = Field(default=0.0)
    conversion_value: float = Field(default=0.0)


class AdsKeywordDaily(SQLModel, table=True):
    """
    Daily keyword performance metrics from Google Ads.

    Stores performance data for individual keywords on a daily basis.
    """

    __tablename__ = "ads_keyword_daily"
    __table_args__ = (Index("ix_ads_keyword_project_date", "project_id", "date"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    date: date_type = Field(index=True)
    campaign_id: str = Field(max_length=100)
    ad_group_id: str = Field(max_length=100)
    criterion_id: str = Field(max_length=100)

    # Keyword details
    keyword_text: str = Field(max_length=500, index=True)
    match_type: str = Field(max_length=20)  # BROAD, PHRASE, EXACT

    # Metrics
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    cost_micros: int = Field(default=0)
    conversions: float = Field(default=0.0)
    average_cpc_micros: int = Field(default=0)
    quality_score: int | None = Field(default=None)
    final_url: str | None = Field(default=None, max_length=2048)


class TransparencyCreative(SQLModel, table=True):
    """
    Competitor ads from transparency datasets (Google Ads Transparency, Meta Ad Library).

    Stores creative content and metadata for competitive analysis.
    """

    __tablename__ = "transparency_creatives"
    __table_args__ = (Index("ix_transparency_advertiser", "advertiser_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_key: str = Field(max_length=50)  # e.g., "google_ads_transparency", "meta"
    advertiser_id: str = Field(max_length=100, index=True)
    advertiser_name: str = Field(max_length=255)
    creative_id: str = Field(max_length=100)

    # Creative content
    headline: str = Field(max_length=500)
    description: str = Field(max_length=2000)
    image_url: str | None = Field(default=None, max_length=2048)
    landing_url: str | None = Field(default=None, max_length=2048)

    # Metadata
    first_seen: date_type
    last_seen: date_type
    geo_targeting: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )


class TrafficDaily(SQLModel, table=True):
    """
    Multi-source traffic data aggregated daily.

    Stores traffic metrics from various sources:
    - GA4: sessions, users, pageviews, bounce_rate, avg_session_duration
    - GSC: clicks, impressions (organic search)
    - CrUX: lcp_p75, fid_p75, cls_p75 (Core Web Vitals)
    - CSV: custom uploaded data
    """

    __tablename__ = "traffic_daily"
    __table_args__ = (
        Index("ix_traffic_project_date_source", "project_id", "date", "source_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    date: date_type = Field(index=True)
    source_key: str = Field(max_length=50)  # ga4, gsc, crux, csv

    # GA4-specific metrics
    sessions: int | None = Field(default=None)
    users: int | None = Field(default=None)
    pageviews: int | None = Field(default=None)
    bounce_rate: float | None = Field(default=None)
    avg_session_duration: float | None = Field(default=None)

    # GSC-specific metrics (organic search)
    clicks: int | None = Field(default=None)
    impressions: int | None = Field(default=None)

    # CrUX-specific metrics (Core Web Vitals)
    lcp_p75: float | None = Field(default=None)  # Largest Contentful Paint (ms)
    fid_p75: float | None = Field(default=None)  # First Input Delay (ms)
    cls_p75: float | None = Field(default=None)  # Cumulative Layout Shift (score)

    # Flexible dimensions storage (device, country, page, etc.)
    dimensions_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )


# ==================== API Response Models ====================


class CampaignRow(SQLModel):
    """API response row for campaign performance."""

    campaign_id: str
    campaign_name: str
    campaign_status: str
    impressions: int
    clicks: int
    cost_micros: int
    conversions: float
    conversion_value: float


class CampaignsResponse(SQLModel):
    """API response for campaigns endpoint."""

    data: list[CampaignRow]
    total: int


class PaidKeywordRow(SQLModel):
    """API response row for paid keyword performance."""

    keyword_text: str
    match_type: str
    impressions: int
    clicks: int
    cost_micros: int
    conversions: float
    average_cpc_micros: int
    quality_score: int | None


class OverlapRow(SQLModel):
    """API response row for organic/paid keyword overlap analysis."""

    keyword: str
    organic_position: float
    paid_position: float
    organic_clicks: int
    paid_clicks: int
    total_clicks: int


class OverlapResponse(SQLModel):
    """API response for keyword overlap endpoint."""

    data: list[OverlapRow]
    total: int


class TrafficPanelRow(SQLModel):
    """API response row for traffic panel (time series data)."""

    date: date_type
    sessions: int | None
    users: int | None
    pageviews: int | None
    bounce_rate: float | None
    avg_session_duration: float | None
    organic_clicks: int | None
    paid_clicks: int | None


class TrafficPanelResponse(SQLModel):
    """API response for traffic panel endpoint."""

    data: list[TrafficPanelRow]
    total: int
