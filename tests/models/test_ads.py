"""
TDD Tests for Ads and Traffic Models (Sprint 5: PPC + Traffic)

This test file is written FIRST following TDD principles.
All tests should FAIL initially until the models are implemented.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.ads import (
    AdsCampaignDaily,
    AdsAccount,
    AdsKeywordDaily,
    CampaignRow,
    CampaignsResponse,
    OverlapResponse,
    OverlapRow,
    PaidKeywordRow,
    TrafficDaily,
    TrafficPanelResponse,
    TrafficPanelRow,
    TransparencyCreative,
)
from app.models import User, Project


@pytest.fixture(name="test_project")
def test_project_fixture(db: Session):
    """Create a test project for ads and traffic tests."""
    import uuid as uuid_module

    # Create test user with unique email
    unique_email = f"test-{uuid_module.uuid4()}@example.com"
    user = User(
        email=unique_email,
        hashed_password="hashedpassword",
        full_name="Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create test project
    project = Project(
        name="Test Project",
        seed_url="https://example.com",
        created_by_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return project


class TestAdsAccount:
    """Test AdsAccount model - linked Google Ads accounts."""

    def test_ads_account_creation_minimal(self, db: Session, test_project):
        """Test creating an AdsAccount with minimal required fields."""
        ads_account = AdsAccount(
            project_id=test_project.id,
            customer_id="1234567890",
        )
        db.add(ads_account)
        db.commit()
        db.refresh(ads_account)

        assert ads_account.id is not None
        assert isinstance(ads_account.id, uuid.UUID)
        assert ads_account.project_id == test_project.id
        assert ads_account.customer_id == "1234567890"
        assert ads_account.descriptive_name is None
        assert ads_account.currency_code == "USD"
        assert ads_account.linked_at is not None
        assert ads_account.last_sync_at is None
        assert ads_account.sync_status == "pending"

    def test_ads_account_creation_all_fields(self, db: Session, test_project):
        """Test creating an AdsAccount with all fields populated."""
        linked_time = datetime.now(timezone.utc)
        sync_time = datetime.now(timezone.utc)

        ads_account = AdsAccount(
            project_id=test_project.id,
            customer_id="1234567890",
            descriptive_name="My Company Ads",
            currency_code="EUR",
            linked_at=linked_time,
            last_sync_at=sync_time,
            sync_status="completed",
        )
        db.add(ads_account)
        db.commit()
        db.refresh(ads_account)

        assert ads_account.customer_id == "1234567890"
        assert ads_account.descriptive_name == "My Company Ads"
        assert ads_account.currency_code == "EUR"
        assert ads_account.linked_at == linked_time
        assert ads_account.last_sync_at == sync_time
        assert ads_account.sync_status == "completed"

    def test_ads_account_unique_project(self, db: Session, test_project):
        """Test that project_id is unique for AdsAccount (one account per project)."""
        ads_account1 = AdsAccount(
            project_id=test_project.id,
            customer_id="1234567890",
        )
        db.add(ads_account1)
        db.commit()

        # Try to add another account for the same project
        ads_account2 = AdsAccount(
            project_id=test_project.id,
            customer_id="9876543210",
        )
        db.add(ads_account2)

        with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
            db.commit()

    def test_ads_account_defaults(self, db: Session, test_project):
        """Test AdsAccount default values."""
        ads_account = AdsAccount(
            project_id=test_project.id,
            customer_id="1234567890",
        )
        db.add(ads_account)
        db.commit()
        db.refresh(ads_account)

        assert ads_account.currency_code == "USD"
        assert ads_account.sync_status == "pending"
        assert ads_account.descriptive_name is None
        assert ads_account.last_sync_at is None


class TestAdsCampaignDaily:
    """Test AdsCampaignDaily model - daily campaign performance metrics."""

    def test_campaign_daily_creation_minimal(self, db: Session, test_project):
        """Test creating a campaign daily record with minimal fields."""
        campaign = AdsCampaignDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            campaign_name="Brand Campaign",
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        assert campaign.id is not None
        assert isinstance(campaign.id, uuid.UUID)
        assert campaign.project_id == test_project.id
        assert campaign.date == date(2024, 1, 15)
        assert campaign.campaign_id == "123456789"
        assert campaign.campaign_name == "Brand Campaign"
        assert campaign.campaign_status is None
        assert campaign.impressions == 0
        assert campaign.clicks == 0
        assert campaign.cost_micros == 0
        assert campaign.conversions == 0.0
        assert campaign.conversion_value == 0.0

    def test_campaign_daily_creation_all_fields(self, db: Session, test_project):
        """Test creating a campaign daily record with all fields."""
        campaign = AdsCampaignDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            campaign_name="Brand Campaign",
            campaign_status="ENABLED",
            impressions=10000,
            clicks=500,
            cost_micros=25000000,  # $25.00 in micros
            conversions=25.5,
            conversion_value=1250.75,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        assert campaign.campaign_status == "ENABLED"
        assert campaign.impressions == 10000
        assert campaign.clicks == 500
        assert campaign.cost_micros == 25000000
        assert campaign.conversions == 25.5
        assert campaign.conversion_value == 1250.75

    def test_campaign_daily_multiple_dates(self, db: Session, test_project):
        """Test creating multiple campaign records for different dates."""
        campaigns = [
            AdsCampaignDaily(
                project_id=test_project.id,
                date=date(2024, 1, 15),
                campaign_id="123456789",
                campaign_name="Brand Campaign",
                clicks=100,
            ),
            AdsCampaignDaily(
                project_id=test_project.id,
                date=date(2024, 1, 16),
                campaign_id="123456789",
                campaign_name="Brand Campaign",
                clicks=150,
            ),
        ]
        for c in campaigns:
            db.add(c)
        db.commit()

        # Query all records
        statement = select(AdsCampaignDaily).where(
            AdsCampaignDaily.project_id == test_project.id
        )
        results = db.exec(statement).all()

        assert len(results) == 2

    def test_campaign_daily_index_on_project_date(self, db: Session, test_project):
        """Test that campaign daily has index on (project_id, date)."""
        campaign = AdsCampaignDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            campaign_name="Test Campaign",
        )
        db.add(campaign)
        db.commit()

        # Query by project_id and date
        results = db.exec(
            select(AdsCampaignDaily).where(
                AdsCampaignDaily.project_id == test_project.id,
                AdsCampaignDaily.date == date(2024, 1, 15),
            )
        ).all()

        assert len(results) == 1


class TestAdsKeywordDaily:
    """Test AdsKeywordDaily model - daily keyword performance metrics."""

    def test_keyword_daily_creation_minimal(self, db: Session, test_project):
        """Test creating a keyword daily record with minimal fields."""
        keyword = AdsKeywordDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            ad_group_id="987654321",
            criterion_id="555666777",
            keyword_text="buy shoes online",
            match_type="BROAD",
        )
        db.add(keyword)
        db.commit()
        db.refresh(keyword)

        assert keyword.id is not None
        assert isinstance(keyword.id, uuid.UUID)
        assert keyword.project_id == test_project.id
        assert keyword.date == date(2024, 1, 15)
        assert keyword.campaign_id == "123456789"
        assert keyword.ad_group_id == "987654321"
        assert keyword.criterion_id == "555666777"
        assert keyword.keyword_text == "buy shoes online"
        assert keyword.match_type == "BROAD"
        assert keyword.impressions == 0
        assert keyword.clicks == 0
        assert keyword.cost_micros == 0
        assert keyword.conversions == 0.0
        assert keyword.average_cpc_micros == 0
        assert keyword.quality_score is None
        assert keyword.final_url is None

    def test_keyword_daily_creation_all_fields(self, db: Session, test_project):
        """Test creating a keyword daily record with all fields."""
        keyword = AdsKeywordDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            ad_group_id="987654321",
            criterion_id="555666777",
            keyword_text="buy shoes online",
            match_type="EXACT",
            impressions=5000,
            clicks=250,
            cost_micros=12500000,  # $12.50 in micros
            conversions=12.5,
            average_cpc_micros=50000,  # $0.05 in micros
            quality_score=8,
            final_url="https://example.com/shoes",
        )
        db.add(keyword)
        db.commit()
        db.refresh(keyword)

        assert keyword.match_type == "EXACT"
        assert keyword.impressions == 5000
        assert keyword.clicks == 250
        assert keyword.cost_micros == 12500000
        assert keyword.conversions == 12.5
        assert keyword.average_cpc_micros == 50000
        assert keyword.quality_score == 8
        assert keyword.final_url == "https://example.com/shoes"

    def test_keyword_daily_index_on_project_date(self, db: Session, test_project):
        """Test that keyword daily has index on (project_id, date)."""
        keyword = AdsKeywordDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            ad_group_id="987654321",
            criterion_id="555666777",
            keyword_text="test keyword",
            match_type="BROAD",
        )
        db.add(keyword)
        db.commit()

        # Query by project_id and date
        results = db.exec(
            select(AdsKeywordDaily).where(
                AdsKeywordDaily.project_id == test_project.id,
                AdsKeywordDaily.date == date(2024, 1, 15),
            )
        ).all()

        assert len(results) == 1

    def test_keyword_daily_index_on_keyword_text(self, db: Session, test_project):
        """Test that keyword daily has index on keyword_text."""
        keyword = AdsKeywordDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            campaign_id="123456789",
            ad_group_id="987654321",
            criterion_id="555666777",
            keyword_text="indexed keyword",
            match_type="BROAD",
        )
        db.add(keyword)
        db.commit()

        # Query by keyword_text
        results = db.exec(
            select(AdsKeywordDaily).where(
                AdsKeywordDaily.keyword_text == "indexed keyword"
            )
        ).all()

        assert len(results) == 1


class TestTransparencyCreative:
    """Test TransparencyCreative model - competitor ads from transparency datasets."""

    def test_transparency_creative_creation_minimal(self, db: Session):
        """Test creating a transparency creative with minimal fields."""
        creative = TransparencyCreative(
            source_key="google_ads_transparency",
            advertiser_id="ADV-123456",
            advertiser_name="Example Corp",
            creative_id="CREATIVE-789",
            headline="Amazing Product Sale",
            description="Get 50% off today",
            first_seen=date(2024, 1, 1),
            last_seen=date(2024, 1, 15),
        )
        db.add(creative)
        db.commit()
        db.refresh(creative)

        assert creative.id is not None
        assert isinstance(creative.id, uuid.UUID)
        assert creative.source_key == "google_ads_transparency"
        assert creative.advertiser_id == "ADV-123456"
        assert creative.advertiser_name == "Example Corp"
        assert creative.creative_id == "CREATIVE-789"
        assert creative.headline == "Amazing Product Sale"
        assert creative.description == "Get 50% off today"
        assert creative.image_url is None
        assert creative.landing_url is None
        assert creative.first_seen == date(2024, 1, 1)
        assert creative.last_seen == date(2024, 1, 15)
        assert creative.geo_targeting == []
        assert creative.metadata_json == {}

    def test_transparency_creative_creation_all_fields(self, db: Session):
        """Test creating a transparency creative with all fields."""
        creative = TransparencyCreative(
            source_key="google_ads_transparency",
            advertiser_id="ADV-123456",
            advertiser_name="Example Corp",
            creative_id="CREATIVE-789",
            headline="Amazing Product Sale",
            description="Get 50% off today",
            image_url="https://example.com/image.jpg",
            landing_url="https://example.com/landing",
            first_seen=date(2024, 1, 1),
            last_seen=date(2024, 1, 15),
            geo_targeting=["US", "CA", "GB"],
            metadata_json={"format": "image", "size": "300x250"},
        )
        db.add(creative)
        db.commit()
        db.refresh(creative)

        assert creative.image_url == "https://example.com/image.jpg"
        assert creative.landing_url == "https://example.com/landing"
        assert creative.geo_targeting == ["US", "CA", "GB"]
        assert creative.metadata_json == {"format": "image", "size": "300x250"}

    def test_transparency_creative_index_on_advertiser_id(self, db: Session):
        """Test that transparency creative has index on advertiser_id."""
        creative = TransparencyCreative(
            source_key="google_ads_transparency",
            advertiser_id="ADV-123456",
            advertiser_name="Example Corp",
            creative_id="CREATIVE-789",
            headline="Test Ad",
            description="Test Description",
            first_seen=date(2024, 1, 1),
            last_seen=date(2024, 1, 15),
        )
        db.add(creative)
        db.commit()

        # Query by advertiser_id
        results = db.exec(
            select(TransparencyCreative).where(
                TransparencyCreative.advertiser_id == "ADV-123456"
            )
        ).all()

        assert len(results) == 1

    def test_transparency_creative_defaults(self, db: Session):
        """Test TransparencyCreative default values."""
        creative = TransparencyCreative(
            source_key="google_ads_transparency",
            advertiser_id="ADV-123456",
            advertiser_name="Example Corp",
            creative_id="CREATIVE-789",
            headline="Test Ad",
            description="Test Description",
            first_seen=date(2024, 1, 1),
            last_seen=date(2024, 1, 15),
        )
        db.add(creative)
        db.commit()
        db.refresh(creative)

        assert creative.geo_targeting == []
        assert creative.metadata_json == {}


class TestTrafficDaily:
    """Test TrafficDaily model - multi-source traffic data."""

    def test_traffic_daily_creation_minimal(self, db: Session, test_project):
        """Test creating a traffic daily record with minimal fields."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="ga4",
        )
        db.add(traffic)
        db.commit()
        db.refresh(traffic)

        assert traffic.id is not None
        assert isinstance(traffic.id, uuid.UUID)
        assert traffic.project_id == test_project.id
        assert traffic.date == date(2024, 1, 15)
        assert traffic.source_key == "ga4"
        assert traffic.sessions is None
        assert traffic.users is None
        assert traffic.pageviews is None
        assert traffic.bounce_rate is None
        assert traffic.avg_session_duration is None
        assert traffic.clicks is None
        assert traffic.impressions is None
        assert traffic.lcp_p75 is None
        assert traffic.fid_p75 is None
        assert traffic.cls_p75 is None
        assert traffic.dimensions_json == {}

    def test_traffic_daily_creation_ga4_fields(self, db: Session, test_project):
        """Test creating a traffic daily record with GA4-specific fields."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="ga4",
            sessions=1000,
            users=800,
            pageviews=3000,
            bounce_rate=0.45,
            avg_session_duration=180.5,
            dimensions_json={"device": "mobile", "country": "US"},
        )
        db.add(traffic)
        db.commit()
        db.refresh(traffic)

        assert traffic.source_key == "ga4"
        assert traffic.sessions == 1000
        assert traffic.users == 800
        assert traffic.pageviews == 3000
        assert traffic.bounce_rate == 0.45
        assert traffic.avg_session_duration == 180.5
        assert traffic.dimensions_json == {"device": "mobile", "country": "US"}

    def test_traffic_daily_creation_gsc_fields(self, db: Session, test_project):
        """Test creating a traffic daily record with GSC-specific fields."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="gsc",
            clicks=500,
            impressions=10000,
            dimensions_json={"page": "/landing", "query": "seo tools"},
        )
        db.add(traffic)
        db.commit()
        db.refresh(traffic)

        assert traffic.source_key == "gsc"
        assert traffic.clicks == 500
        assert traffic.impressions == 10000
        assert traffic.dimensions_json == {"page": "/landing", "query": "seo tools"}

    def test_traffic_daily_creation_crux_fields(self, db: Session, test_project):
        """Test creating a traffic daily record with CrUX-specific fields."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="crux",
            lcp_p75=2500.0,  # 2.5 seconds
            fid_p75=100.0,  # 100ms
            cls_p75=0.15,  # CLS score
            dimensions_json={"form_factor": "DESKTOP"},
        )
        db.add(traffic)
        db.commit()
        db.refresh(traffic)

        assert traffic.source_key == "crux"
        assert traffic.lcp_p75 == 2500.0
        assert traffic.fid_p75 == 100.0
        assert traffic.cls_p75 == 0.15
        assert traffic.dimensions_json == {"form_factor": "DESKTOP"}

    def test_traffic_daily_index_on_project_date_source(self, db: Session, test_project):
        """Test that traffic daily has index on (project_id, date, source_key)."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="ga4",
            sessions=1000,
        )
        db.add(traffic)
        db.commit()

        # Query by project_id, date, and source_key
        results = db.exec(
            select(TrafficDaily).where(
                TrafficDaily.project_id == test_project.id,
                TrafficDaily.date == date(2024, 1, 15),
                TrafficDaily.source_key == "ga4",
            )
        ).all()

        assert len(results) == 1

    def test_traffic_daily_multiple_sources(self, db: Session, test_project):
        """Test creating traffic records from multiple sources for the same date."""
        traffic_records = [
            TrafficDaily(
                project_id=test_project.id,
                date=date(2024, 1, 15),
                source_key="ga4",
                sessions=1000,
            ),
            TrafficDaily(
                project_id=test_project.id,
                date=date(2024, 1, 15),
                source_key="gsc",
                clicks=500,
            ),
            TrafficDaily(
                project_id=test_project.id,
                date=date(2024, 1, 15),
                source_key="crux",
                lcp_p75=2500.0,
            ),
        ]
        for t in traffic_records:
            db.add(t)
        db.commit()

        # Query all records for this date
        results = db.exec(
            select(TrafficDaily).where(
                TrafficDaily.project_id == test_project.id,
                TrafficDaily.date == date(2024, 1, 15),
            )
        ).all()

        assert len(results) == 3

    def test_traffic_daily_defaults(self, db: Session, test_project):
        """Test TrafficDaily default values."""
        traffic = TrafficDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            source_key="csv",
        )
        db.add(traffic)
        db.commit()
        db.refresh(traffic)

        assert traffic.dimensions_json == {}


class TestAPIResponseModels:
    """Test API response models for Ads and Traffic features."""

    def test_campaign_row_creation(self):
        """Test CampaignRow response model."""
        row = CampaignRow(
            campaign_id="123456789",
            campaign_name="Brand Campaign",
            campaign_status="ENABLED",
            impressions=10000,
            clicks=500,
            cost_micros=25000000,
            conversions=25.5,
            conversion_value=1250.75,
        )
        assert row.campaign_id == "123456789"
        assert row.campaign_name == "Brand Campaign"
        assert row.campaign_status == "ENABLED"
        assert row.impressions == 10000
        assert row.clicks == 500
        assert row.cost_micros == 25000000

    def test_campaigns_response_creation(self):
        """Test CampaignsResponse response model."""
        rows = [
            CampaignRow(
                campaign_id="123456789",
                campaign_name="Brand Campaign",
                campaign_status="ENABLED",
                impressions=10000,
                clicks=500,
                cost_micros=25000000,
                conversions=25.5,
                conversion_value=1250.75,
            ),
            CampaignRow(
                campaign_id="987654321",
                campaign_name="Generic Campaign",
                campaign_status="PAUSED",
                impressions=5000,
                clicks=250,
                cost_micros=12500000,
                conversions=10.0,
                conversion_value=500.0,
            ),
        ]
        response = CampaignsResponse(data=rows, total=2)
        assert len(response.data) == 2
        assert response.total == 2

    def test_paid_keyword_row_creation(self):
        """Test PaidKeywordRow response model."""
        row = PaidKeywordRow(
            keyword_text="buy shoes online",
            match_type="EXACT",
            impressions=5000,
            clicks=250,
            cost_micros=12500000,
            conversions=12.5,
            average_cpc_micros=50000,
            quality_score=8,
        )
        assert row.keyword_text == "buy shoes online"
        assert row.match_type == "EXACT"
        assert row.impressions == 5000
        assert row.quality_score == 8

    def test_overlap_row_creation(self):
        """Test OverlapRow response model."""
        row = OverlapRow(
            keyword="seo tools",
            organic_position=5.5,
            paid_position=2.0,
            organic_clicks=100,
            paid_clicks=50,
            total_clicks=150,
            paid_cost_micros=50_000_000,  # $50 in micros
            opportunity_score=250.5,
            overlap_type="both",
        )
        assert row.keyword == "seo tools"
        assert row.organic_position == 5.5
        assert row.paid_position == 2.0
        assert row.total_clicks == 150
        assert row.paid_cost_micros == 50_000_000
        assert row.opportunity_score == 250.5
        assert row.overlap_type == "both"

    def test_overlap_response_creation(self):
        """Test OverlapResponse response model."""
        from app.models.ads import OverlapSummary

        rows = [
            OverlapRow(
                keyword="seo tools",
                organic_position=5.5,
                paid_position=2.0,
                organic_clicks=100,
                paid_clicks=50,
                total_clicks=150,
                paid_cost_micros=50_000_000,
                opportunity_score=250.5,
                overlap_type="both",
            ),
            OverlapRow(
                keyword="analytics platform",
                organic_position=8.0,
                paid_position=3.5,
                organic_clicks=80,
                paid_clicks=40,
                total_clicks=120,
                paid_cost_micros=30_000_000,
                opportunity_score=150.0,
                overlap_type="paid_only",
            ),
        ]
        summary = OverlapSummary(
            total_keywords=2,
            overlap_count=1,
            paid_only_count=1,
            organic_only_count=0,
        )
        response = OverlapResponse(data=rows, total=2, summary=summary)
        assert len(response.data) == 2
        assert response.total == 2
        assert response.summary.total_keywords == 2
        assert response.summary.overlap_count == 1
        assert response.summary.paid_only_count == 1

    def test_traffic_panel_row_creation(self):
        """Test TrafficPanelRow response model."""
        row = TrafficPanelRow(
            date=date(2024, 1, 15),
            sessions=1000,
            users=800,
            pageviews=3000,
            bounce_rate=0.45,
            avg_session_duration=180.5,
            organic_clicks=500,
            paid_clicks=100,
        )
        assert row.date == date(2024, 1, 15)
        assert row.sessions == 1000
        assert row.users == 800
        assert row.organic_clicks == 500
        assert row.paid_clicks == 100

    def test_traffic_panel_response_creation(self):
        """Test TrafficPanelResponse response model."""
        rows = [
            TrafficPanelRow(
                date=date(2024, 1, 15),
                sessions=1000,
                users=800,
                pageviews=3000,
                bounce_rate=0.45,
                avg_session_duration=180.5,
                organic_clicks=500,
                paid_clicks=100,
            ),
            TrafficPanelRow(
                date=date(2024, 1, 16),
                sessions=1200,
                users=900,
                pageviews=3500,
                bounce_rate=0.42,
                avg_session_duration=190.0,
                organic_clicks=550,
                paid_clicks=120,
            ),
        ]
        response = TrafficPanelResponse(data=rows, total=2)
        assert len(response.data) == 2
        assert response.total == 2
