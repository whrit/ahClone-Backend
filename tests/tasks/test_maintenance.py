"""
Tests for maintenance tasks (cleanup_old_data, health_check, etc.)
Sprint 6: Hardening - Retention policies and cleanup
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.models.ads import AdsCampaignDaily, AdsKeywordDaily
from app.models.audit import AuditIssue, AuditRun, AuditStatus, CrawledPage
from app.models.gsc import GSCPageDaily, GSCQueryDaily
from app.models.job import JobRun, JobStatus, JobType
from app.models.links import BacklinkEdge, LinkSnapshot
from app.models.project import Project
from app.models.serp import KeywordTarget, RankObservation, SerpSnapshot
from app.tasks.maintenance import cleanup_audit_runs, cleanup_old_data, health_check
from tests.utils.project import create_random_project


@pytest.fixture
def test_project(db: Session) -> Project:
    """Create a test project."""
    return create_random_project(db)


@pytest.fixture
def old_job_runs(db: Session, test_project: Project) -> list[JobRun]:
    """Create old JobRun records (older than retention period)."""
    retention_days = getattr(settings, "RETENTION_JOB_RUNS", 7)
    old_date = datetime.now(timezone.utc) - timedelta(days=retention_days + 1)

    runs = []
    for i in range(5):
        run = JobRun(
            job_type=JobType.AUDIT,
            project_id=test_project.id,
            status=JobStatus.COMPLETED,
            queued_at=old_date - timedelta(hours=i),
        )
        db.add(run)
        runs.append(run)

    db.commit()
    return runs


@pytest.fixture
def recent_job_runs(db: Session, test_project: Project) -> list[JobRun]:
    """Create recent JobRun records (within retention period)."""
    retention_days = getattr(settings, "RETENTION_JOB_RUNS", 7)
    recent_date = datetime.now(timezone.utc) - timedelta(days=retention_days - 1)

    runs = []
    for i in range(3):
        run = JobRun(
            job_type=JobType.GSC_SYNC,
            project_id=test_project.id,
            status=JobStatus.COMPLETED,
            queued_at=recent_date + timedelta(hours=i),
        )
        db.add(run)
        runs.append(run)

    db.commit()
    return runs


@pytest.fixture
def old_serp_snapshots(db: Session, test_project: Project) -> list[SerpSnapshot]:
    """Create old SerpSnapshot records."""
    retention_days = getattr(settings, "RETENTION_SERP_SNAPSHOTS", 90)
    old_date = datetime.now(timezone.utc) - timedelta(days=retention_days + 1)

    # Create keyword target first
    keyword = KeywordTarget(
        project_id=test_project.id,
        keyword="test keyword",
        locale="en-US",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    snapshots = []
    for i in range(5):
        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=old_date - timedelta(days=i),
            results_json={"results": []},
        )
        db.add(snapshot)
        snapshots.append(snapshot)

    db.commit()
    return snapshots


@pytest.fixture
def recent_serp_snapshots(
    db: Session, test_project: Project
) -> list[SerpSnapshot]:
    """Create recent SerpSnapshot records."""
    retention_days = getattr(settings, "RETENTION_SERP_SNAPSHOTS", 90)
    recent_date = datetime.now(timezone.utc) - timedelta(days=retention_days - 1)

    # Create keyword target
    keyword = KeywordTarget(
        project_id=test_project.id,
        keyword="recent keyword",
        locale="en-US",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    snapshots = []
    for i in range(3):
        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=recent_date + timedelta(days=i),
            results_json={"results": []},
        )
        db.add(snapshot)
        snapshots.append(snapshot)

    db.commit()
    return snapshots


@pytest.fixture
def old_audit_runs(db: Session, test_project: Project) -> list[AuditRun]:
    """Create old AuditRun records (more than 10 for project)."""
    old_date = datetime.now(timezone.utc) - timedelta(days=40)

    runs = []
    for i in range(15):
        run = AuditRun(
            project_id=test_project.id,
            status=AuditStatus.COMPLETED,
            created_at=old_date - timedelta(days=i),
            started_at=old_date - timedelta(days=i),
            finished_at=old_date - timedelta(days=i) + timedelta(hours=1),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # Add some crawled pages and issues
        page = CrawledPage(
            audit_run_id=run.id,
            url=f"https://example.com/page{i}",
            final_url=f"https://example.com/page{i}",
            depth=1,
            status_code=200,
            crawled_at=old_date - timedelta(days=i),
        )
        db.add(page)

        issue = AuditIssue(
            audit_run_id=run.id,
            page_url=f"https://example.com/page{i}",
            issue_type="missing_title",
            severity="high",
        )
        db.add(issue)

        runs.append(run)

    db.commit()
    return runs


@pytest.fixture
def old_link_snapshots(db: Session) -> list[LinkSnapshot]:
    """Create old LinkSnapshot records."""
    retention_days = getattr(settings, "RETENTION_LINK_SNAPSHOTS", 60)
    old_date = datetime.now(timezone.utc) - timedelta(days=retention_days + 1)

    snapshots = []
    for i in range(5):
        snapshot = LinkSnapshot(
            crawl_id=f"CC-MAIN-2024-{i:02d}",
            ingested_at=old_date - timedelta(days=i),
            status="completed",
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        # Add some backlink edges
        edge = BacklinkEdge(
            snapshot_id=snapshot.id,
            source_url=f"https://source{i}.com",
            target_url="https://example.com",
            source_domain=f"source{i}.com",
            target_domain="example.com",
            first_seen=old_date - timedelta(days=i),
            last_seen=old_date - timedelta(days=i),
        )
        db.add(edge)

        snapshots.append(snapshot)

    db.commit()
    return snapshots


@pytest.fixture
def recent_link_snapshots(db: Session) -> list[LinkSnapshot]:
    """Create recent LinkSnapshot records."""
    retention_days = getattr(settings, "RETENTION_LINK_SNAPSHOTS", 60)
    recent_date = datetime.now(timezone.utc) - timedelta(days=retention_days - 1)

    snapshots = []
    for i in range(3):
        snapshot = LinkSnapshot(
            crawl_id=f"CC-MAIN-2024-{20+i:02d}",
            ingested_at=recent_date + timedelta(days=i),
            status="completed",
        )
        db.add(snapshot)
        snapshots.append(snapshot)

    db.commit()
    return snapshots


@pytest.fixture
def old_gsc_data(db: Session, test_project: Project):
    """Create old GSC data."""
    retention_days = getattr(settings, "RETENTION_GSC_DAILY", 365)
    old_date = (datetime.now(timezone.utc) - timedelta(days=retention_days + 1)).date()

    records = []
    for i in range(5):
        query_record = GSCQueryDaily(
            project_id=test_project.id,
            date=old_date - timedelta(days=i),
            query=f"old query {i}",
            clicks=10,
            impressions=100,
            ctr=0.1,
            position=5.0,
        )
        db.add(query_record)
        records.append(query_record)

        page_record = GSCPageDaily(
            project_id=test_project.id,
            date=old_date - timedelta(days=i),
            page=f"https://example.com/old{i}",
            clicks=10,
            impressions=100,
            ctr=0.1,
            position=5.0,
        )
        db.add(page_record)
        records.append(page_record)

    db.commit()
    return records


@pytest.fixture
def old_ads_data(db: Session, test_project: Project):
    """Create old Ads data."""
    retention_days = getattr(settings, "RETENTION_ADS_DAILY", 365)
    old_date = (datetime.now(timezone.utc) - timedelta(days=retention_days + 1)).date()

    records = []
    for i in range(5):
        campaign_record = AdsCampaignDaily(
            project_id=test_project.id,
            date=old_date - timedelta(days=i),
            campaign_id=f"campaign{i}",
            campaign_name=f"Campaign {i}",
            impressions=1000,
            clicks=50,
            cost_micros=1000000,
        )
        db.add(campaign_record)
        records.append(campaign_record)

        keyword_record = AdsKeywordDaily(
            project_id=test_project.id,
            date=old_date - timedelta(days=i),
            campaign_id=f"campaign{i}",
            ad_group_id=f"adgroup{i}",
            criterion_id=f"criterion{i}",
            keyword_text=f"keyword {i}",
            match_type="EXACT",
            impressions=100,
            clicks=5,
            cost_micros=100000,
        )
        db.add(keyword_record)
        records.append(keyword_record)

    db.commit()
    return records


class TestCleanupOldData:
    """Tests for cleanup_old_data task."""

    def test_cleanup_deletes_old_job_runs(
        self, db: Session, old_job_runs: list[JobRun], recent_job_runs: list[JobRun]
    ):
        """Test that old JobRun records are deleted."""
        # Verify initial state
        assert len(old_job_runs) == 5
        assert len(recent_job_runs) == 3

        # Run cleanup
        result = cleanup_old_data()

        # Verify old runs deleted, recent runs kept
        db.expire_all()
        all_runs = db.exec(select(JobRun)).all()
        assert len(all_runs) == 3  # Only recent runs remain
        assert result["job_runs_deleted"] == 5

    def test_cleanup_deletes_old_serp_snapshots(
        self,
        db: Session,
        old_serp_snapshots: list[SerpSnapshot],
        recent_serp_snapshots: list[SerpSnapshot],
    ):
        """Test that old SerpSnapshot records are deleted."""
        assert len(old_serp_snapshots) == 5
        assert len(recent_serp_snapshots) == 3

        result = cleanup_old_data()

        db.expire_all()
        all_snapshots = db.exec(select(SerpSnapshot)).all()
        assert len(all_snapshots) == 3
        assert result["serp_snapshots_deleted"] == 5

    def test_cleanup_keeps_last_10_audit_runs(
        self, db: Session, old_audit_runs: list[AuditRun]
    ):
        """Test that only last 10 audit runs per project are kept."""
        assert len(old_audit_runs) == 15

        # Store IDs before cleanup (objects will be deleted)
        audit_run_data = [
            {"id": run.id, "created_at": run.created_at} for run in old_audit_runs
        ]

        result = cleanup_old_data()

        db.expire_all()
        remaining_runs = db.exec(select(AuditRun)).all()
        # Should keep only last 10
        assert len(remaining_runs) == 10
        assert result["audit_runs_deleted"] == 5

        # Verify the 5 oldest audit runs (by created_at) were deleted
        # Sort by created_at ascending (oldest first)
        sorted_data = sorted(audit_run_data, key=lambda r: r["created_at"])
        remaining_ids = {run.id for run in remaining_runs}

        # The 5 oldest should be deleted
        for data in sorted_data[:5]:
            assert data["id"] not in remaining_ids

        # The 10 newest should remain
        for data in sorted_data[5:]:
            assert data["id"] in remaining_ids

    def test_cleanup_deletes_old_link_snapshots(
        self,
        db: Session,
        old_link_snapshots: list[LinkSnapshot],
        recent_link_snapshots: list[LinkSnapshot],
    ):
        """Test that old LinkSnapshot records are deleted."""
        assert len(old_link_snapshots) == 5
        assert len(recent_link_snapshots) == 3

        result = cleanup_old_data()

        db.expire_all()
        all_snapshots = db.exec(select(LinkSnapshot)).all()
        assert len(all_snapshots) == 3
        assert result["link_snapshots_deleted"] == 5

    def test_cleanup_deletes_old_gsc_data(
        self, db: Session, old_gsc_data, test_project: Project
    ):
        """Test that old GSC daily data is deleted."""
        result = cleanup_old_data()

        db.expire_all()
        remaining_query = db.exec(select(GSCQueryDaily)).all()
        remaining_page = db.exec(select(GSCPageDaily)).all()

        assert len(remaining_query) == 0
        assert len(remaining_page) == 0
        assert result["gsc_query_deleted"] >= 5
        assert result["gsc_page_deleted"] >= 5

    def test_cleanup_deletes_old_ads_data(
        self, db: Session, old_ads_data, test_project: Project
    ):
        """Test that old Ads daily data is deleted."""
        result = cleanup_old_data()

        db.expire_all()
        remaining_campaign = db.exec(select(AdsCampaignDaily)).all()
        remaining_keyword = db.exec(select(AdsKeywordDaily)).all()

        assert len(remaining_campaign) == 0
        assert len(remaining_keyword) == 0
        assert result["ads_campaign_deleted"] >= 5
        assert result["ads_keyword_deleted"] >= 5

    def test_cleanup_respects_foreign_key_constraints(
        self, db: Session, old_audit_runs: list[AuditRun]
    ):
        """Test that cleanup properly handles cascading deletes."""
        # Count child records before cleanup
        pages_before = db.exec(select(CrawledPage)).all()
        issues_before = db.exec(select(AuditIssue)).all()

        assert len(pages_before) == 15  # One per audit run
        assert len(issues_before) == 15

        result = cleanup_old_data()

        db.expire_all()

        # After cleanup, child records of deleted audit runs should be gone
        pages_after = db.exec(select(CrawledPage)).all()
        issues_after = db.exec(select(AuditIssue)).all()

        # 5 audit runs deleted, so 5 pages and 5 issues should be deleted
        assert len(pages_after) == 10
        assert len(issues_after) == 10

    def test_cleanup_returns_counts(
        self,
        db: Session,
        old_job_runs: list[JobRun],
        old_serp_snapshots: list[SerpSnapshot],
        old_audit_runs: list[AuditRun],
    ):
        """Test that cleanup returns proper counts of deleted records."""
        result = cleanup_old_data()

        assert isinstance(result, dict)
        assert "job_runs_deleted" in result
        assert "serp_snapshots_deleted" in result
        assert "audit_runs_deleted" in result
        assert "link_snapshots_deleted" in result
        assert "gsc_query_deleted" in result
        assert "gsc_page_deleted" in result
        assert "ads_campaign_deleted" in result
        assert "ads_keyword_deleted" in result

        # Verify counts are integers
        assert isinstance(result["job_runs_deleted"], int)
        assert isinstance(result["serp_snapshots_deleted"], int)
        assert isinstance(result["audit_runs_deleted"], int)

    def test_cleanup_with_no_old_data(self, db: Session, test_project: Project):
        """Test cleanup when there's no old data to delete."""
        result = cleanup_old_data()

        assert result["job_runs_deleted"] == 0
        assert result["serp_snapshots_deleted"] == 0
        assert result["audit_runs_deleted"] == 0


class TestCleanupAuditRuns:
    """Tests for cleanup_audit_runs task."""

    def test_cleanup_specific_project(
        self, db: Session, old_audit_runs: list[AuditRun], test_project: Project
    ):
        """Test cleanup for a specific project."""
        # Create another project with audit runs
        other_project = create_random_project(db)

        # Add 5 runs to other project
        for i in range(5):
            run = AuditRun(
                project_id=other_project.id,
                status=AuditStatus.COMPLETED,
                created_at=datetime.now(timezone.utc) - timedelta(days=i),
            )
            db.add(run)
        db.commit()

        # Should have 15 runs for test_project, 5 for other_project
        all_runs = db.exec(select(AuditRun)).all()
        assert len(all_runs) == 20

        # Cleanup only test_project
        result = cleanup_audit_runs(project_id=str(test_project.id))

        db.expire_all()
        remaining_runs = db.exec(select(AuditRun)).all()

        # Should have 10 from test_project + 5 from other_project
        assert len(remaining_runs) == 15
        assert result["audit_runs_deleted"] == 5

        # Verify other project's runs untouched
        other_runs = db.exec(
            select(AuditRun).where(AuditRun.project_id == other_project.id)
        ).all()
        assert len(other_runs) == 5

    def test_cleanup_all_projects(
        self, db: Session, old_audit_runs: list[AuditRun], test_project: Project
    ):
        """Test cleanup for all projects when project_id is None."""
        # Create another project with 15 audit runs
        other_project = create_random_project(db)

        for i in range(15):
            run = AuditRun(
                project_id=other_project.id,
                status=AuditStatus.COMPLETED,
                created_at=datetime.now(timezone.utc) - timedelta(days=i),
            )
            db.add(run)
        db.commit()

        # Total: 15 + 15 = 30 audit runs
        all_runs = db.exec(select(AuditRun)).all()
        assert len(all_runs) == 30

        # Cleanup all projects
        result = cleanup_audit_runs(project_id=None)

        db.expire_all()
        remaining_runs = db.exec(select(AuditRun)).all()

        # Should keep 10 per project = 20 total
        assert len(remaining_runs) == 20
        assert result["audit_runs_deleted"] == 10

    def test_cleanup_cascades_to_children(
        self, db: Session, old_audit_runs: list[AuditRun], test_project: Project
    ):
        """Test that cleanup properly deletes associated pages and issues."""
        pages_before = db.exec(select(CrawledPage)).all()
        issues_before = db.exec(select(AuditIssue)).all()

        assert len(pages_before) == 15
        assert len(issues_before) == 15

        result = cleanup_audit_runs(project_id=str(test_project.id))

        db.expire_all()

        pages_after = db.exec(select(CrawledPage)).all()
        issues_after = db.exec(select(AuditIssue)).all()

        # 5 deleted, so should have 10 remaining
        assert len(pages_after) == 10
        assert len(issues_after) == 10


class TestHealthCheck:
    """Tests for health_check task."""

    @patch("app.tasks.maintenance.celery_app")
    def test_health_check_success(self, mock_celery):
        """Test health check returns healthy status."""
        # Mock successful Redis/broker connection
        mock_celery.broker_connection.return_value.__enter__.return_value.connect.return_value = None

        result = health_check()

        assert isinstance(result, dict)
        assert result["status"] == "healthy"
        assert "db_connected" in result
        assert result["db_connected"] is True
        assert "redis_connected" in result
        assert result["redis_connected"] is True
        assert "timestamp" in result

    @patch("app.tasks.maintenance.engine")
    def test_health_check_db_failure(self, mock_engine):
        """Test health check when database connection fails."""
        # Mock database connection failure
        mock_engine.connect.side_effect = Exception("Database connection failed")

        result = health_check()

        assert result["status"] == "unhealthy"
        assert result["db_connected"] is False
        assert "error" in result

    @patch("app.tasks.maintenance.celery_app")
    def test_health_check_redis_failure(self, mock_celery):
        """Test health check when Redis connection fails."""
        # Mock Redis connection failure
        mock_celery.broker_connection.return_value.__enter__.side_effect = Exception(
            "Redis connection failed"
        )

        result = health_check()

        assert result["status"] == "unhealthy"
        assert result["redis_connected"] is False


class TestRetentionSettings:
    """Tests for retention settings configuration."""

    def test_retention_settings_exist(self):
        """Test that all retention settings are defined."""
        assert hasattr(settings, "RETENTION_JOB_RUNS")
        assert hasattr(settings, "RETENTION_SERP_SNAPSHOTS")
        assert hasattr(settings, "RETENTION_AUDIT_RUNS")
        assert hasattr(settings, "RETENTION_LINK_SNAPSHOTS")
        assert hasattr(settings, "RETENTION_GSC_DAILY")
        assert hasattr(settings, "RETENTION_ADS_DAILY")

    def test_retention_settings_are_integers(self):
        """Test that retention settings are integer values."""
        assert isinstance(settings.RETENTION_JOB_RUNS, int)
        assert isinstance(settings.RETENTION_SERP_SNAPSHOTS, int)
        assert isinstance(settings.RETENTION_AUDIT_RUNS, int)
        assert isinstance(settings.RETENTION_LINK_SNAPSHOTS, int)
        assert isinstance(settings.RETENTION_GSC_DAILY, int)
        assert isinstance(settings.RETENTION_ADS_DAILY, int)

    def test_retention_settings_positive(self):
        """Test that retention settings are positive values."""
        assert settings.RETENTION_JOB_RUNS > 0
        assert settings.RETENTION_SERP_SNAPSHOTS > 0
        assert settings.RETENTION_AUDIT_RUNS > 0
        assert settings.RETENTION_LINK_SNAPSHOTS > 0
        assert settings.RETENTION_GSC_DAILY > 0
        assert settings.RETENTION_ADS_DAILY > 0
