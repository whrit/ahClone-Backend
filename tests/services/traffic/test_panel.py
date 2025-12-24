"""Tests for Traffic Panel Service (TDD)."""
# ruff: noqa: ARG001
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, delete

from app import crud
from app.models import User
from app.models.ads import TrafficDaily
from app.models.gsc import GSCQueryDaily
from app.models.project import Project
from app.services.traffic.panel import TrafficPanelService


@pytest.fixture
def test_project(db: Session) -> Project:
    """Create a test project for traffic testing."""
    # Get or create a test user
    user = crud.get_user_by_email(session=db, email="test@example.com")
    if not user:
        user = User(
            email="test@example.com",
            hashed_password="test",
            is_active=True,
            is_superuser=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Create test project
    project = Project(
        name="Test Traffic Project",
        seed_url="https://example.com",
        created_by_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def traffic_panel_service(db: Session) -> TrafficPanelService:
    """Create a TrafficPanelService instance."""
    return TrafficPanelService(db)


@pytest.fixture
def clean_traffic_data(db: Session):
    """Clean up traffic data before and after each test."""
    # Clean before
    statement = delete(TrafficDaily)
    db.execute(statement)
    statement = delete(GSCQueryDaily)
    db.execute(statement)
    db.commit()

    yield

    # Clean after
    statement = delete(TrafficDaily)
    db.execute(statement)
    statement = delete(GSCQueryDaily)
    db.execute(statement)
    db.commit()


class TestTrafficPanelService:
    """Test suite for TrafficPanelService."""

    def test_get_panel_data_with_all_sources(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test get_panel_data combines data from all sources."""
        # Arrange: Create test data for all sources
        today = date.today()
        test_date = today - timedelta(days=1)

        # GA4 data
        ga4_data = TrafficDaily(
            project_id=test_project.id,
            date=test_date,
            source_key="ga4",
            sessions=1500,
            users=1200,
            pageviews=3500,
        )
        db.add(ga4_data)

        # CrUX data
        crux_data = TrafficDaily(
            project_id=test_project.id,
            date=test_date,
            source_key="crux",
            lcp_p75=2500.0,
            fid_p75=100.0,
            cls_p75=0.1,
        )
        db.add(crux_data)

        # GSC data
        for i in range(3):
            gsc_query = GSCQueryDaily(
                project_id=test_project.id,
                date=test_date,
                query=f"test query {i}",
                clicks=100,
                impressions=1000,
                ctr=0.1,
                position=5.0,
            )
            db.add(gsc_query)
        db.commit()

        # Act: Get panel data
        panel_data = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=7
        )

        # Assert: Should return combined data
        assert isinstance(panel_data, list)
        assert len(panel_data) == 7  # 7 days of data

        # Find the test date in results
        test_date_row = next((row for row in panel_data if row["date"] == test_date), None)
        assert test_date_row is not None

        # Check GA4 data
        assert test_date_row["ga4_sessions"] == 1500
        assert test_date_row["ga4_users"] == 1200
        assert test_date_row["ga4_pageviews"] == 3500

        # Check GSC data (3 queries * 100 clicks each)
        assert test_date_row["gsc_clicks"] == 300

        # Check CrUX data
        assert test_date_row["lcp"] == 2500.0
        assert test_date_row["cls"] == 0.1

    def test_get_panel_data_missing_sources(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test get_panel_data handles missing data sources gracefully."""
        # Arrange: Create only GA4 data, no GSC or CrUX
        today = date.today()
        test_date = today - timedelta(days=1)

        ga4_data = TrafficDaily(
            project_id=test_project.id,
            date=test_date,
            source_key="ga4",
            sessions=500,
            users=400,
            pageviews=1000,
        )
        db.add(ga4_data)
        db.commit()

        # Act: Get panel data
        panel_data = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=7
        )

        # Assert: Should return data with None for missing sources
        assert isinstance(panel_data, list)
        assert len(panel_data) == 7

        test_date_row = next((row for row in panel_data if row["date"] == test_date), None)
        assert test_date_row is not None
        assert test_date_row["ga4_sessions"] == 500
        assert test_date_row["gsc_clicks"] is None
        assert test_date_row["lcp"] is None
        assert test_date_row["cls"] is None

    def test_get_panel_data_date_range_generation(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test that get_panel_data generates correct date range."""
        # Arrange: No data in database
        today = date.today()

        # Act: Get panel data for 14 days
        panel_data = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=14
        )

        # Assert: Should return 14 days of data, even if empty
        assert len(panel_data) == 14

        # Check dates are in correct order (oldest to newest)
        expected_start = today - timedelta(days=13)
        expected_end = today

        assert panel_data[0]["date"] == expected_start
        assert panel_data[-1]["date"] == expected_end

        # All dates should have None values for missing data
        for row in panel_data:
            assert row["ga4_sessions"] is None
            assert row["gsc_clicks"] is None
            assert row["lcp"] is None

    def test_get_ga4_data(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test _get_ga4_data returns correct sessions/users/pageviews."""
        # Arrange: Create GA4 data for multiple days
        today = date.today()

        for day_offset in range(3):
            test_date = today - timedelta(days=day_offset)
            ga4_data = TrafficDaily(
                project_id=test_project.id,
                date=test_date,
                source_key="ga4",
                sessions=1000 + day_offset * 100,
                users=800 + day_offset * 80,
                pageviews=2500 + day_offset * 250,
            )
            db.add(ga4_data)
        db.commit()

        # Act: Get GA4 data
        start_date = today - timedelta(days=2)
        end_date = today
        ga4_data_dict = traffic_panel_service._get_ga4_data(
            project_id=test_project.id,
            start_date=start_date,
            end_date=end_date
        )

        # Assert: Should return dict with date keys
        assert isinstance(ga4_data_dict, dict)
        assert len(ga4_data_dict) == 3

        # Check data for each date
        for day_offset in range(3):
            test_date = today - timedelta(days=day_offset)
            assert test_date in ga4_data_dict

            day_data = ga4_data_dict[test_date]
            assert day_data["sessions"] == 1000 + day_offset * 100
            assert day_data["users"] == 800 + day_offset * 80
            assert day_data["pageviews"] == 2500 + day_offset * 250

    def test_get_gsc_clicks_aggregates_by_date(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test _get_gsc_clicks aggregates clicks by date from GSCQueryDaily."""
        # Arrange: Create multiple queries for same date
        today = date.today()
        test_date = today - timedelta(days=1)

        queries = [
            ("query 1", 50),
            ("query 2", 75),
            ("query 3", 100),
            ("query 4", 25),
        ]

        for query, clicks in queries:
            gsc_query = GSCQueryDaily(
                project_id=test_project.id,
                date=test_date,
                query=query,
                clicks=clicks,
                impressions=1000,
                ctr=0.1,
                position=5.0,
            )
            db.add(gsc_query)
        db.commit()

        # Act: Get GSC clicks
        start_date = today - timedelta(days=1)
        end_date = today
        gsc_clicks_dict = traffic_panel_service._get_gsc_clicks(
            project_id=test_project.id,
            start_date=start_date,
            end_date=end_date
        )

        # Assert: Should aggregate all clicks for the date
        assert isinstance(gsc_clicks_dict, dict)
        assert test_date in gsc_clicks_dict
        assert gsc_clicks_dict[test_date] == 250  # 50 + 75 + 100 + 25

    def test_get_gsc_clicks_multiple_dates(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test _get_gsc_clicks handles multiple dates."""
        # Arrange: Create data for multiple dates
        today = date.today()

        for day_offset in range(5):
            test_date = today - timedelta(days=day_offset)
            for i in range(3):  # 3 queries per day
                gsc_query = GSCQueryDaily(
                    project_id=test_project.id,
                    date=test_date,
                    query=f"query {i}",
                    clicks=10 * (day_offset + 1),  # Different clicks per day
                    impressions=100,
                    ctr=0.1,
                    position=5.0,
                )
                db.add(gsc_query)
        db.commit()

        # Act: Get GSC clicks
        start_date = today - timedelta(days=4)
        end_date = today
        gsc_clicks_dict = traffic_panel_service._get_gsc_clicks(
            project_id=test_project.id,
            start_date=start_date,
            end_date=end_date
        )

        # Assert: Should aggregate clicks per date
        assert len(gsc_clicks_dict) == 5

        for day_offset in range(5):
            test_date = today - timedelta(days=day_offset)
            expected_clicks = 10 * (day_offset + 1) * 3  # 3 queries
            assert gsc_clicks_dict[test_date] == expected_clicks

    def test_get_crux_data(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test _get_crux_data returns Core Web Vitals metrics."""
        # Arrange: Create CrUX data
        today = date.today()

        for day_offset in range(3):
            test_date = today - timedelta(days=day_offset)
            crux_data = TrafficDaily(
                project_id=test_project.id,
                date=test_date,
                source_key="crux",
                lcp_p75=2000.0 + day_offset * 100,
                fid_p75=50.0 + day_offset * 10,
                cls_p75=0.05 + day_offset * 0.01,
            )
            db.add(crux_data)
        db.commit()

        # Act: Get CrUX data
        start_date = today - timedelta(days=2)
        end_date = today
        crux_data_dict = traffic_panel_service._get_crux_data(
            project_id=test_project.id,
            start_date=start_date,
            end_date=end_date
        )

        # Assert: Should return dict with date keys
        assert isinstance(crux_data_dict, dict)
        assert len(crux_data_dict) == 3

        # Check data for each date
        for day_offset in range(3):
            test_date = today - timedelta(days=day_offset)
            assert test_date in crux_data_dict

            day_data = crux_data_dict[test_date]
            assert day_data["lcp"] == 2000.0 + day_offset * 100
            assert day_data["fid"] == 50.0 + day_offset * 10
            assert day_data["cls"] == 0.05 + day_offset * 0.01

    def test_import_csv_data(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test import_csv_data creates TrafficDaily records."""
        # Arrange: Prepare CSV data
        csv_data = [
            {
                "date": "2024-01-01",
                "sessions": "1500",
                "users": "1200",
                "pageviews": "3500",
            },
            {
                "date": "2024-01-02",
                "sessions": "1600",
                "users": "1300",
                "pageviews": "3700",
            },
            {
                "date": "2024-01-03",
                "sessions": "1400",
                "users": "1100",
                "pageviews": "3300",
            },
        ]

        # Act: Import CSV data
        imported_count = traffic_panel_service.import_csv_data(
            project_id=test_project.id,
            csv_data=csv_data
        )

        # Assert: Should import all records
        assert imported_count == 3

        # Verify data was inserted
        from sqlmodel import select
        statement = select(TrafficDaily).where(
            TrafficDaily.project_id == test_project.id,
            TrafficDaily.source_key == "csv"
        )
        results = db.exec(statement).all()

        assert len(results) == 3
        assert results[0].sessions == 1500
        assert results[0].users == 1200
        assert results[0].pageviews == 3500

    def test_import_csv_data_handles_invalid_rows(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test import_csv_data skips invalid rows gracefully."""
        # Arrange: CSV data with some invalid rows
        csv_data = [
            {
                "date": "2024-01-01",
                "sessions": "1500",
                "users": "1200",
                "pageviews": "3500",
            },
            {
                "date": "invalid-date",  # Invalid date format
                "sessions": "1600",
                "users": "1300",
                "pageviews": "3700",
            },
            {
                "date": "2024-01-03",
                "sessions": "not-a-number",  # Invalid number
                "users": "1100",
                "pageviews": "3300",
            },
            {
                "date": "2024-01-04",
                "sessions": "1700",
                "users": "1400",
                "pageviews": "3800",
            },
        ]

        # Act: Import CSV data
        imported_count = traffic_panel_service.import_csv_data(
            project_id=test_project.id,
            csv_data=csv_data
        )

        # Assert: Should only import valid records
        assert imported_count == 2  # Only rows 1 and 4 are valid

        # Verify only valid data was inserted
        from sqlmodel import select
        statement = select(TrafficDaily).where(
            TrafficDaily.project_id == test_project.id,
            TrafficDaily.source_key == "csv"
        )
        results = db.exec(statement).all()

        assert len(results) == 2

    def test_import_csv_data_with_optional_fields(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test import_csv_data handles optional fields."""
        # Arrange: CSV data with additional optional fields
        csv_data = [
            {
                "date": "2024-01-01",
                "sessions": "1500",
                "users": "1200",
                "pageviews": "3500",
                "bounce_rate": "0.45",
                "avg_session_duration": "180.5",
            },
        ]

        # Act: Import CSV data
        imported_count = traffic_panel_service.import_csv_data(
            project_id=test_project.id,
            csv_data=csv_data
        )

        # Assert: Should import with optional fields
        assert imported_count == 1

        from sqlmodel import select
        statement = select(TrafficDaily).where(
            TrafficDaily.project_id == test_project.id,
            TrafficDaily.source_key == "csv"
        )
        result = db.exec(statement).first()

        assert result is not None
        assert result.bounce_rate == 0.45
        assert result.avg_session_duration == 180.5

    def test_period_days_parameter(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test period_days parameter controls date range."""
        # Test different period values
        for period in [7, 14, 28, 90]:
            panel_data = traffic_panel_service.get_panel_data(
                project_id=test_project.id,
                period_days=period
            )

            assert len(panel_data) == period

            # Verify date range
            today = date.today()
            expected_start = today - timedelta(days=period - 1)

            assert panel_data[0]["date"] == expected_start
            assert panel_data[-1]["date"] == today

    def test_empty_database_returns_empty_rows(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test that empty database returns rows with None values."""
        # Arrange: No data in database

        # Act: Get panel data
        panel_data = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=7
        )

        # Assert: Should return 7 rows with None values
        assert len(panel_data) == 7

        for row in panel_data:
            assert row["ga4_sessions"] is None
            assert row["ga4_users"] is None
            assert row["ga4_pageviews"] is None
            assert row["gsc_clicks"] is None
            assert row["lcp"] is None
            assert row["cls"] is None

    def test_only_project_data_returned(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test that only data for specified project is returned."""
        # Arrange: Create another project with data
        user = crud.get_user_by_email(session=db, email="test@example.com")
        other_project = Project(
            name="Other Project",
            seed_url="https://other.com",
            created_by_id=user.id,
        )
        db.add(other_project)
        db.commit()
        db.refresh(other_project)

        today = date.today()
        test_date = today - timedelta(days=1)

        # Add data for both projects
        ga4_test = TrafficDaily(
            project_id=test_project.id,
            date=test_date,
            source_key="ga4",
            sessions=1000,
            users=800,
        )
        ga4_other = TrafficDaily(
            project_id=other_project.id,
            date=test_date,
            source_key="ga4",
            sessions=5000,
            users=4000,
        )
        db.add(ga4_test)
        db.add(ga4_other)
        db.commit()

        # Act: Get panel data for test_project
        panel_data = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=7
        )

        # Assert: Should only include test_project data
        test_date_row = next((row for row in panel_data if row["date"] == test_date), None)
        assert test_date_row is not None
        assert test_date_row["ga4_sessions"] == 1000
        assert test_date_row["ga4_users"] == 800

    def test_uuid_and_string_project_id_support(
        self,
        db: Session,
        test_project: Project,
        traffic_panel_service: TrafficPanelService,
        clean_traffic_data
    ):
        """Test that both UUID and string project IDs are supported."""
        # Arrange: Create test data
        today = date.today()
        test_date = today - timedelta(days=1)

        ga4_data = TrafficDaily(
            project_id=test_project.id,
            date=test_date,
            source_key="ga4",
            sessions=1500,
            users=1200,
        )
        db.add(ga4_data)
        db.commit()

        # Act: Get panel data using UUID
        panel_data_uuid = traffic_panel_service.get_panel_data(
            project_id=test_project.id,
            period_days=7
        )

        # Act: Get panel data using string UUID
        panel_data_str = traffic_panel_service.get_panel_data(
            project_id=str(test_project.id),
            period_days=7
        )

        # Assert: Both should return same results
        assert len(panel_data_uuid) == len(panel_data_str)
        assert panel_data_uuid[0] == panel_data_str[0]
