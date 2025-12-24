"""
TDD Tests for Audit Models

This test file is written FIRST following TDD principles.
All tests should FAIL initially until the models are implemented.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models.audit import (
    AuditIssue,
    AuditIssuePublic,
    AuditIssuesPublic,
    AuditLinkEdge,
    AuditRun,
    AuditRunConfig,
    AuditRunPublic,
    AuditRunsPublic,
    AuditRunStats,
    AuditStatus,
    CrawledPage,
    CrawledPagePublic,
    CrawledPagesPublic,
    ISSUE_SEVERITY_MAP,
    IssueSeverity,
    IssueType,
)


# Helper function to create test user and project
def create_test_user_and_project(db: Session, email_suffix: str):
    """Helper to create a test user and project."""
    from app.models import User, Project
    from app.core.security import get_password_hash

    user = User(
        email=f"testaudit{email_suffix}@example.com",
        hashed_password=get_password_hash("testpass123"),
        full_name=f"Test User {email_suffix}"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = Project(
        name=f"Test Project {email_suffix}",
        seed_url=f"https://example{email_suffix}.com",
        created_by_id=user.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return user, project


class TestEnums:
    """Test all Enum definitions."""

    def test_audit_status_enum_values(self):
        """Test AuditStatus enum has all required values."""
        assert AuditStatus.QUEUED == "queued"
        assert AuditStatus.CRAWLING == "crawling"
        assert AuditStatus.RENDERING == "rendering"
        assert AuditStatus.ANALYZING == "analyzing"
        assert AuditStatus.DIFFING == "diffing"
        assert AuditStatus.COMPLETED == "completed"
        assert AuditStatus.FAILED == "failed"

    def test_issue_severity_enum_values(self):
        """Test IssueSeverity enum has all required values."""
        assert IssueSeverity.CRITICAL == "critical"
        assert IssueSeverity.HIGH == "high"
        assert IssueSeverity.MEDIUM == "medium"
        assert IssueSeverity.LOW == "low"

    def test_issue_type_enum_values(self):
        """Test IssueType enum has all required issue types."""
        # Server & redirect issues
        assert IssueType.SERVER_ERROR_5XX == "server_error_5xx"
        assert IssueType.REDIRECT_LOOP == "redirect_loop"
        assert IssueType.REDIRECT_CHAIN == "redirect_chain"
        assert IssueType.BROKEN_INTERNAL_LINK == "broken_internal_link"
        assert IssueType.CLIENT_ERROR_4XX == "client_error_4xx"

        # Title issues
        assert IssueType.MISSING_TITLE == "missing_title"
        assert IssueType.DUPLICATE_TITLE == "duplicate_title"
        assert IssueType.TITLE_TOO_LONG == "title_too_long"
        assert IssueType.TITLE_TOO_SHORT == "title_too_short"

        # Meta description issues
        assert IssueType.MISSING_META_DESCRIPTION == "missing_meta_description"
        assert IssueType.META_DESC_TOO_LONG == "meta_desc_too_long"
        assert IssueType.META_DESC_TOO_SHORT == "meta_desc_too_short"

        # H1 issues
        assert IssueType.MISSING_H1 == "missing_h1"
        assert IssueType.MULTIPLE_H1 == "multiple_h1"

        # Canonical issues
        assert IssueType.MISSING_CANONICAL == "missing_canonical"
        assert IssueType.CANONICAL_MISMATCH == "canonical_mismatch"

        # Security & content issues
        assert IssueType.NON_HTTPS == "non_https"
        assert IssueType.THIN_CONTENT == "thin_content"
        assert IssueType.ORPHAN_PAGE == "orphan_page"

    def test_issue_severity_map_completeness(self):
        """Test ISSUE_SEVERITY_MAP has mapping for all IssueTypes."""
        for issue_type in IssueType:
            assert issue_type in ISSUE_SEVERITY_MAP, f"Missing severity mapping for {issue_type}"
            assert isinstance(ISSUE_SEVERITY_MAP[issue_type], IssueSeverity)

    def test_issue_severity_map_values(self):
        """Test specific severity mappings are correct."""
        # Critical issues
        assert ISSUE_SEVERITY_MAP[IssueType.SERVER_ERROR_5XX] == IssueSeverity.CRITICAL
        assert ISSUE_SEVERITY_MAP[IssueType.REDIRECT_LOOP] == IssueSeverity.CRITICAL
        assert ISSUE_SEVERITY_MAP[IssueType.BROKEN_INTERNAL_LINK] == IssueSeverity.CRITICAL

        # High severity issues
        assert ISSUE_SEVERITY_MAP[IssueType.REDIRECT_CHAIN] == IssueSeverity.HIGH
        assert ISSUE_SEVERITY_MAP[IssueType.CLIENT_ERROR_4XX] == IssueSeverity.HIGH
        assert ISSUE_SEVERITY_MAP[IssueType.MISSING_TITLE] == IssueSeverity.HIGH
        assert ISSUE_SEVERITY_MAP[IssueType.DUPLICATE_TITLE] == IssueSeverity.HIGH

        # Medium severity issues
        assert ISSUE_SEVERITY_MAP[IssueType.MISSING_META_DESCRIPTION] == IssueSeverity.MEDIUM
        assert ISSUE_SEVERITY_MAP[IssueType.MISSING_H1] == IssueSeverity.MEDIUM
        assert ISSUE_SEVERITY_MAP[IssueType.MULTIPLE_H1] == IssueSeverity.MEDIUM

        # Low severity issues
        assert ISSUE_SEVERITY_MAP[IssueType.TITLE_TOO_LONG] == IssueSeverity.LOW
        assert ISSUE_SEVERITY_MAP[IssueType.TITLE_TOO_SHORT] == IssueSeverity.LOW


class TestAuditRunConfig:
    """Test AuditRunConfig non-table model."""

    def test_audit_run_config_creation(self):
        """Test creating an AuditRunConfig instance."""
        config = AuditRunConfig(
            max_pages=500,
            max_depth=5,
            crawl_concurrency=10,
            enable_js_rendering=True
        )
        assert config.max_pages == 500
        assert config.max_depth == 5
        assert config.crawl_concurrency == 10
        assert config.enable_js_rendering is True

    def test_audit_run_config_serialization(self):
        """Test AuditRunConfig can be serialized to dict."""
        config = AuditRunConfig(max_pages=1000, max_depth=3)
        config_dict = config.model_dump()
        assert isinstance(config_dict, dict)
        assert config_dict["max_pages"] == 1000
        assert config_dict["max_depth"] == 3


class TestAuditRunStats:
    """Test AuditRunStats non-table model."""

    def test_audit_run_stats_creation(self):
        """Test creating an AuditRunStats instance."""
        stats = AuditRunStats(
            total_pages=100,
            pages_ok=90,
            pages_redirect=5,
            pages_error=5,
            total_issues=25,
            issues_critical=2,
            issues_high=8,
            issues_medium=10,
            issues_low=5
        )
        assert stats.total_pages == 100
        assert stats.pages_ok == 90
        assert stats.total_issues == 25
        assert stats.issues_critical == 2

    def test_audit_run_stats_serialization(self):
        """Test AuditRunStats can be serialized to dict."""
        stats = AuditRunStats(
            total_pages=50,
            pages_ok=45,
            pages_redirect=3,
            pages_error=2
        )
        stats_dict = stats.model_dump()
        assert isinstance(stats_dict, dict)
        assert stats_dict["total_pages"] == 50


class TestAuditRunModel:
    """Test AuditRun table model."""

    def test_audit_run_creation(self, db: Session):
        """Test creating an AuditRun record."""
        user, project = create_test_user_and_project(db, "1")

        # Create audit run
        config = AuditRunConfig(max_pages=100, max_depth=5)
        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.QUEUED,
            config=config.model_dump(),
            progress_pct=0.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        assert audit_run.id is not None
        assert isinstance(audit_run.id, uuid.UUID)
        assert audit_run.project_id == project.id
        assert audit_run.status == AuditStatus.QUEUED
        assert audit_run.config["max_pages"] == 100
        assert audit_run.progress_pct == 0.0
        assert audit_run.created_at is not None

    def test_audit_run_json_fields(self, db: Session):
        """Test JSON field serialization for config and stats."""
        user, project = create_test_user_and_project(db, "2")

        config = AuditRunConfig(max_pages=200, enable_js_rendering=True)
        stats = AuditRunStats(total_pages=150, pages_ok=140, pages_error=10)

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.COMPLETED,
            config=config.model_dump(),
            stats=stats.model_dump(),
            progress_pct=100.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        # Verify JSON fields can be accessed as dicts
        assert isinstance(audit_run.config, dict)
        assert audit_run.config["max_pages"] == 200
        assert audit_run.config["enable_js_rendering"] is True

        assert isinstance(audit_run.stats, dict)
        assert audit_run.stats["total_pages"] == 150
        assert audit_run.stats["pages_ok"] == 140

    def test_audit_run_relationship_to_project(self, db: Session):
        """Test relationship between AuditRun and Project."""
        user, project = create_test_user_and_project(db, "3")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.CRAWLING,
            config={},
            progress_pct=50.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        # Test the relationship
        assert audit_run.project is not None
        assert audit_run.project.id == project.id
        assert audit_run.project.name == "Test Project 3"


class TestCrawledPageModel:
    """Test CrawledPage table model."""

    def test_crawled_page_creation(self, db: Session):
        """Test creating a CrawledPage record."""
        user, project = create_test_user_and_project(db, "4")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.CRAWLING,
            config={},
            progress_pct=25.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        # Create crawled page
        page = CrawledPage(
            audit_run_id=audit_run.id,
            url="https://example4.com/page1",
            final_url="https://example4.com/page1",
            depth=1,
            status_code=200,
            content_type="text/html",
            response_time_ms=150,
            title="Test Page",
            meta_description="Test description",
            h1_count=1,
            first_h1="Main Heading",
            word_count=500,
            crawled_at=datetime.now(timezone.utc)
        )
        db.add(page)
        db.commit()
        db.refresh(page)

        assert page.id is not None
        assert isinstance(page.id, uuid.UUID)
        assert page.audit_run_id == audit_run.id
        assert page.url == "https://example4.com/page1"
        assert page.status_code == 200
        assert page.title == "Test Page"
        assert page.word_count == 500

    def test_crawled_page_redirect_chain_json(self, db: Session):
        """Test redirect_chain JSON field."""
        user, project = create_test_user_and_project(db, "5")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.CRAWLING,
            config={},
            progress_pct=30.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        redirect_chain = [
            {"url": "https://example5.com/old", "status": 301},
            {"url": "https://example5.com/newer", "status": 302},
            {"url": "https://example5.com/final", "status": 200}
        ]

        page = CrawledPage(
            audit_run_id=audit_run.id,
            url="https://example5.com/old",
            final_url="https://example5.com/final",
            depth=1,
            status_code=200,
            redirect_chain=redirect_chain,
            crawled_at=datetime.now(timezone.utc)
        )
        db.add(page)
        db.commit()
        db.refresh(page)

        assert page.redirect_chain is not None
        assert isinstance(page.redirect_chain, list)
        assert len(page.redirect_chain) == 3
        assert page.redirect_chain[0]["url"] == "https://example5.com/old"

    def test_crawled_page_relationship_to_audit_run(self, db: Session):
        """Test relationship between CrawledPage and AuditRun."""
        user, project = create_test_user_and_project(db, "6")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.CRAWLING,
            config={},
            progress_pct=40.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        page = CrawledPage(
            audit_run_id=audit_run.id,
            url="https://example6.com/test",
            final_url="https://example6.com/test",
            depth=0,
            status_code=200,
            crawled_at=datetime.now(timezone.utc)
        )
        db.add(page)
        db.commit()
        db.refresh(page)

        # Test relationship
        assert page.audit_run is not None
        assert page.audit_run.id == audit_run.id


class TestAuditIssueModel:
    """Test AuditIssue table model."""

    def test_audit_issue_creation(self, db: Session):
        """Test creating an AuditIssue record."""
        user, project = create_test_user_and_project(db, "7")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.ANALYZING,
            config={},
            progress_pct=75.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        # Create issue
        issue = AuditIssue(
            audit_run_id=audit_run.id,
            page_url="https://example7.com/broken",
            issue_type=IssueType.MISSING_TITLE,
            severity=IssueSeverity.HIGH,
            details={"message": "Page has no title tag"},
            first_seen_run_id=audit_run.id,
            is_new=True
        )
        db.add(issue)
        db.commit()
        db.refresh(issue)

        assert issue.id is not None
        assert isinstance(issue.id, uuid.UUID)
        assert issue.audit_run_id == audit_run.id
        assert issue.page_url == "https://example7.com/broken"
        assert issue.issue_type == IssueType.MISSING_TITLE
        assert issue.severity == IssueSeverity.HIGH
        assert issue.is_new is True

    def test_audit_issue_details_json(self, db: Session):
        """Test details JSON field."""
        user, project = create_test_user_and_project(db, "8")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.ANALYZING,
            config={},
            progress_pct=80.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        details = {
            "message": "Title length exceeds 60 characters",
            "current_length": 75,
            "recommended_max": 60,
            "current_title": "This is a very long title that exceeds the recommended length"
        }

        issue = AuditIssue(
            audit_run_id=audit_run.id,
            page_url="https://example8.com/long-title",
            issue_type=IssueType.TITLE_TOO_LONG,
            severity=IssueSeverity.LOW,
            details=details,
            first_seen_run_id=audit_run.id,
            is_new=False
        )
        db.add(issue)
        db.commit()
        db.refresh(issue)

        assert issue.details is not None
        assert isinstance(issue.details, dict)
        assert issue.details["current_length"] == 75
        assert issue.details["message"] == "Title length exceeds 60 characters"


class TestAuditLinkEdgeModel:
    """Test AuditLinkEdge table model."""

    def test_audit_link_edge_creation(self, db: Session):
        """Test creating an AuditLinkEdge record."""
        user, project = create_test_user_and_project(db, "9")

        audit_run = AuditRun(
            project_id=project.id,
            status=AuditStatus.CRAWLING,
            config={},
            progress_pct=60.0
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)

        # Create link edge
        link = AuditLinkEdge(
            audit_run_id=audit_run.id,
            source_url="https://example9.com/page1",
            target_url="https://example9.com/page2",
            anchor_text="Click here",
            is_internal=True,
            is_followed=True,
            target_status_code=200
        )
        db.add(link)
        db.commit()
        db.refresh(link)

        assert link.id is not None
        assert isinstance(link.id, uuid.UUID)
        assert link.audit_run_id == audit_run.id
        assert link.source_url == "https://example9.com/page1"
        assert link.target_url == "https://example9.com/page2"
        assert link.anchor_text == "Click here"
        assert link.is_internal is True
        assert link.is_followed is True
        assert link.target_status_code == 200


class TestPublicModels:
    """Test Public API response models."""

    def test_audit_run_public_model(self):
        """Test AuditRunPublic model."""
        run_id = uuid.uuid4()
        project_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        public_run = AuditRunPublic(
            id=run_id,
            project_id=project_id,
            status=AuditStatus.COMPLETED,
            config={"max_pages": 100},
            stats={"total_pages": 50},
            started_at=now,
            finished_at=now,
            error_message=None,
            progress_pct=100.0,
            progress_message="Completed",
            created_at=now
        )

        assert public_run.id == run_id
        assert public_run.status == AuditStatus.COMPLETED
        assert public_run.config["max_pages"] == 100

    def test_audit_runs_public_model(self):
        """Test AuditRunsPublic collection model."""
        run_id = uuid.uuid4()
        project_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        public_run = AuditRunPublic(
            id=run_id,
            project_id=project_id,
            status=AuditStatus.COMPLETED,
            config={},
            stats={},
            started_at=now,
            finished_at=now,
            error_message=None,
            progress_pct=100.0,
            progress_message=None,
            created_at=now
        )

        runs_public = AuditRunsPublic(data=[public_run], count=1)

        assert len(runs_public.data) == 1
        assert runs_public.count == 1
        assert runs_public.data[0].id == run_id

    def test_crawled_page_public_model(self):
        """Test CrawledPagePublic model."""
        page_id = uuid.uuid4()
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        public_page = CrawledPagePublic(
            id=page_id,
            audit_run_id=run_id,
            url="https://example.com/test",
            final_url="https://example.com/test",
            depth=1,
            status_code=200,
            content_type="text/html",
            response_time_ms=100,
            redirect_chain=None,
            title="Test Page",
            meta_description="Test description",
            canonical=None,
            h1_count=1,
            first_h1="Main Heading",
            word_count=300,
            meta_robots=None,
            is_rendered=False,
            rendered_at=None,
            rendered_title=None,
            rendered_meta_description=None,
            rendered_h1_count=None,
            rendered_word_count=None,
            content_hash="abc123",
            crawled_at=now
        )

        assert public_page.id == page_id
        assert public_page.url == "https://example.com/test"
        assert public_page.status_code == 200

    def test_audit_issue_public_model(self):
        """Test AuditIssuePublic model."""
        issue_id = uuid.uuid4()
        run_id = uuid.uuid4()

        public_issue = AuditIssuePublic(
            id=issue_id,
            audit_run_id=run_id,
            page_url="https://example.com/issue",
            issue_type=IssueType.MISSING_H1,
            severity=IssueSeverity.MEDIUM,
            details={"message": "No H1 found"},
            first_seen_run_id=run_id,
            is_new=True
        )

        assert public_issue.id == issue_id
        assert public_issue.issue_type == IssueType.MISSING_H1
        assert public_issue.severity == IssueSeverity.MEDIUM
        assert public_issue.is_new is True


class TestModelValidation:
    """Test model validation rules."""

    def test_audit_run_requires_project_id(self, db: Session):
        """Test that AuditRun requires a valid project_id."""
        audit_run = AuditRun(
            project_id=uuid.uuid4(),  # Non-existent project
            status=AuditStatus.QUEUED,
            config={},
            progress_pct=0.0
        )
        db.add(audit_run)

        # Should raise foreign key constraint error
        with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
            db.commit()
        db.rollback()

    def test_crawled_page_requires_audit_run_id(self, db: Session):
        """Test that CrawledPage requires a valid audit_run_id."""
        page = CrawledPage(
            audit_run_id=uuid.uuid4(),  # Non-existent audit run
            url="https://example.com/test",
            final_url="https://example.com/test",
            depth=0,
            status_code=200,
            crawled_at=datetime.now(timezone.utc)
        )
        db.add(page)

        # Should raise foreign key constraint error
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
