"""
Test suite for Celery audit tasks.
Following TDD approach - tests written first.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlmodel import Session, select

import app.tasks.audit  # noqa: F401 - Import to register tasks
from app.core.celery import celery_app
from app.crud import create_user
from app.models import User, UserCreate
from app.models.audit import (
    AuditIssue,
    AuditLinkEdge,
    AuditRun,
    AuditStatus,
    CrawledPage,
    IssueSeverity,
    IssueType,
)
from app.models.project import Project


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user for audit tasks."""
    user = create_user(
        session=db,
        user_create=UserCreate(
            email=f"test-audit-{uuid.uuid4()}@example.com",
            password="test_password",
            is_superuser=False,
        ),
    )
    return user


@pytest.fixture
def test_project(db: Session, test_user: User) -> Project:
    """Create a test project for audit tasks."""
    project = Project(
        id=uuid.uuid4(),
        name="Test Project",
        seed_url="https://example.com",
        description="Test project for audit tasks",
        created_by_id=test_user.id,
        settings={
            "max_pages": 10,
            "max_depth": 2,
            "crawl_concurrency": 2,
            "enable_js_rendering": True,
            "js_render_mode": "hybrid",
            "max_render_pages": 5,
        },
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def test_audit_run(db: Session, test_project: Project) -> AuditRun:
    """Create a test audit run."""
    audit_run = AuditRun(
        id=uuid.uuid4(),
        project_id=test_project.id,
        status=AuditStatus.QUEUED,
        config={
            "max_pages": 10,
            "max_depth": 2,
            "crawl_concurrency": 2,
            "enable_js_rendering": True,
            "js_render_mode": "hybrid",
            "max_render_pages": 5,
            "render_timeout_ms": 30000,
        },
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)
    return audit_run


class TestTaskRegistration:
    """Test that tasks are properly registered with Celery."""

    def test_run_audit_task_is_registered(self):
        """The run_audit task should be registered."""
        assert "app.tasks.audit.run_audit" in celery_app.tasks

    def test_crawl_pages_task_is_registered(self):
        """The crawl_pages task should be registered."""
        assert "app.tasks.audit.crawl_pages" in celery_app.tasks

    def test_render_pages_task_is_registered(self):
        """The render_pages task should be registered."""
        assert "app.tasks.audit.render_pages" in celery_app.tasks

    def test_analyze_pages_task_is_registered(self):
        """The analyze_pages task should be registered."""
        assert "app.tasks.audit.analyze_pages" in celery_app.tasks

    def test_compute_diff_task_is_registered(self):
        """The compute_diff task should be registered."""
        assert "app.tasks.audit.compute_diff" in celery_app.tasks


class TestCrawlPagesTask:
    """Test the crawl_pages task."""

    @patch("app.tasks.audit.Crawler")
    def test_crawl_pages_updates_status_to_crawling(
        self, mock_crawler_class, db: Session, test_audit_run: AuditRun
    ):
        """The crawl_pages task should update status to CRAWLING."""
        # Import task
        from app.tasks.audit import crawl_pages

        # Setup mock crawler
        mock_crawler = MagicMock()
        mock_crawler_class.return_value = mock_crawler

        # Create async generator for crawl results
        async def mock_crawl():
            yield (
                MagicMock(
                    url="https://example.com",
                    final_url="https://example.com",
                    status_code=200,
                    content_type="text/html",
                    response_time_ms=100,
                    redirect_chain=[],
                    html="<html></html>",
                    error=None,
                ),
                MagicMock(
                    title="Test Page",
                    meta_description="Test description",
                    canonical="https://example.com",
                    h1_count=1,
                    first_h1="Test H1",
                    word_count=500,
                    meta_robots=None,
                    internal_links=["https://example.com/page2"],
                    external_links=[],
                    content_hash="abc123",
                ),
                0,  # depth
            )

        mock_crawler.crawl.return_value = mock_crawl()
        mock_crawler.setup = AsyncMock()

        # Run task
        result = crawl_pages(
            str(test_audit_run.project_id), str(test_audit_run.id)
        )

        # Verify status was updated
        db.refresh(test_audit_run)
        assert test_audit_run.status == AuditStatus.CRAWLING
        assert test_audit_run.started_at is not None

    @patch("app.tasks.audit.Crawler")
    def test_crawl_pages_saves_crawled_pages(
        self, mock_crawler_class, db: Session, test_audit_run: AuditRun
    ):
        """The crawl_pages task should save CrawledPage records."""
        from app.tasks.audit import crawl_pages

        # Setup mock crawler
        mock_crawler = MagicMock()
        mock_crawler_class.return_value = mock_crawler

        # Create async generator for crawl results
        async def mock_crawl():
            yield (
                MagicMock(
                    url="https://example.com",
                    final_url="https://example.com",
                    status_code=200,
                    content_type="text/html",
                    response_time_ms=100,
                    redirect_chain=[],
                    html="<html></html>",
                    error=None,
                ),
                MagicMock(
                    title="Test Page",
                    meta_description="Test description",
                    canonical="https://example.com",
                    h1_count=1,
                    first_h1="Test H1",
                    word_count=500,
                    meta_robots=None,
                    internal_links=[],
                    external_links=[],
                    content_hash="abc123",
                ),
                0,
            )

        mock_crawler.crawl.return_value = mock_crawl()
        mock_crawler.setup = AsyncMock()

        # Run task
        result = crawl_pages(
            str(test_audit_run.project_id), str(test_audit_run.id)
        )

        # Verify pages were saved
        statement = select(CrawledPage).where(
            CrawledPage.audit_run_id == test_audit_run.id
        )
        pages = db.exec(statement).all()
        assert len(pages) >= 1
        assert pages[0].url == "https://example.com"
        assert pages[0].status_code == 200

    @patch("app.tasks.audit.Crawler")
    def test_crawl_pages_returns_page_count(
        self, mock_crawler_class, db: Session, test_audit_run: AuditRun
    ):
        """The crawl_pages task should return page count."""
        from app.tasks.audit import crawl_pages

        # Setup mock crawler
        mock_crawler = MagicMock()
        mock_crawler_class.return_value = mock_crawler

        async def mock_crawl():
            for i in range(3):
                yield (
                    MagicMock(
                        url=f"https://example.com/page{i}",
                        final_url=f"https://example.com/page{i}",
                        status_code=200,
                        content_type="text/html",
                        response_time_ms=100,
                        redirect_chain=[],
                        html="<html></html>",
                        error=None,
                    ),
                    MagicMock(
                        title=f"Page {i}",
                        meta_description="Test",
                        canonical=f"https://example.com/page{i}",
                        h1_count=1,
                        first_h1="Test",
                        word_count=500,
                        meta_robots=None,
                        internal_links=[],
                        external_links=[],
                        content_hash=f"hash{i}",
                    ),
                    0,
                )

        mock_crawler.crawl.return_value = mock_crawl()
        mock_crawler.setup = AsyncMock()

        result = crawl_pages(
            str(test_audit_run.project_id), str(test_audit_run.id)
        )

        assert result["pages_crawled"] == 3

    @patch("app.tasks.audit.Crawler")
    def test_crawl_pages_handles_errors(
        self, mock_crawler_class, db: Session, test_audit_run: AuditRun
    ):
        """The crawl_pages task should handle errors and set status to FAILED."""
        from app.tasks.audit import crawl_pages

        # Setup mock to raise exception
        mock_crawler_class.side_effect = Exception("Test error")

        # Run task - should raise after setting status
        with pytest.raises(Exception, match="Test error"):
            result = crawl_pages(
                str(test_audit_run.project_id), str(test_audit_run.id)
            )

        # Verify status was updated to FAILED
        db.refresh(test_audit_run)
        assert test_audit_run.status == AuditStatus.FAILED
        assert "Test error" in test_audit_run.error_message


class TestRenderPagesTask:
    """Test the render_pages task."""

    @patch("app.tasks.audit.Renderer")
    def test_render_pages_skips_if_rendering_disabled(
        self, mock_renderer_class, db: Session, test_audit_run: AuditRun
    ):
        """The render_pages task should skip if enable_js_rendering is False."""
        from app.tasks.audit import render_pages

        # Update config to disable rendering - reassign the whole dict so SQLModel detects change
        config = test_audit_run.config.copy()
        config["enable_js_rendering"] = False
        test_audit_run.config = config
        db.add(test_audit_run)
        db.commit()

        result = render_pages(
            {"pages_crawled": 5},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        assert result["pages_rendered"] == 0
        mock_renderer_class.assert_not_called()

    @patch("app.tasks.audit.Renderer")
    def test_render_pages_updates_status_to_rendering(
        self, mock_renderer_class, db: Session, test_audit_run: AuditRun
    ):
        """The render_pages task should update status to RENDERING."""
        from app.tasks.audit import render_pages

        # Create a crawled page
        page = CrawledPage(
            audit_run_id=test_audit_run.id,
            url="https://example.com",
            final_url="https://example.com",
            depth=0,
            status_code=200,
            title="",
            word_count=10,  # Below threshold
            h1_count=0,
            crawled_at=datetime.now(timezone.utc),
        )
        db.add(page)
        db.commit()

        # Setup mock renderer
        mock_renderer = MagicMock()
        mock_renderer_class.return_value = mock_renderer
        mock_renderer.start = AsyncMock()
        mock_renderer.stop = AsyncMock()
        mock_renderer.render = AsyncMock(
            return_value=MagicMock(
                url="https://example.com",
                html="<html></html>",
                title="Rendered Title",
                meta_description="Rendered desc",
                h1_count=1,
                word_count=500,
                render_time_ms=100,
                error=None,
            )
        )

        result = render_pages(
            {"pages_crawled": 1},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        db.refresh(test_audit_run)
        assert test_audit_run.status == AuditStatus.RENDERING

    @patch("app.tasks.audit.Renderer")
    def test_render_pages_respects_max_render_pages(
        self, mock_renderer_class, db: Session, test_audit_run: AuditRun
    ):
        """The render_pages task should respect max_render_pages limit."""
        from app.tasks.audit import render_pages

        # Set max_render_pages to 2 - reassign the whole dict so SQLModel detects change
        config = test_audit_run.config.copy()
        config["max_render_pages"] = 2
        test_audit_run.config = config
        db.add(test_audit_run)
        db.commit()

        # Create 5 pages that need rendering
        for i in range(5):
            page = CrawledPage(
                audit_run_id=test_audit_run.id,
                url=f"https://example.com/page{i}",
                final_url=f"https://example.com/page{i}",
                depth=0,
                status_code=200,
                title="",
                word_count=10,  # Below threshold
                h1_count=0,
                crawled_at=datetime.now(timezone.utc),
            )
            db.add(page)
        db.commit()

        # Setup mock renderer
        mock_renderer = MagicMock()
        mock_renderer_class.return_value = mock_renderer
        mock_renderer.start = AsyncMock()
        mock_renderer.stop = AsyncMock()
        mock_renderer.render = AsyncMock(
            return_value=MagicMock(
                url="https://example.com",
                html="<html></html>",
                title="Rendered",
                meta_description="Desc",
                h1_count=1,
                word_count=500,
                render_time_ms=100,
                error=None,
            )
        )

        result = render_pages(
            {"pages_crawled": 5},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        # Should only render 2 pages
        assert result["pages_rendered"] == 2


class TestAnalyzePagesTask:
    """Test the analyze_pages task."""

    @patch("app.tasks.audit.IssueAnalyzer")
    @patch("app.tasks.audit.DuplicateDetector")
    def test_analyze_pages_updates_status_to_analyzing(
        self,
        mock_detector_class,
        mock_analyzer_class,
        db: Session,
        test_audit_run: AuditRun,
        test_project: Project,
    ):
        """The analyze_pages task should update status to ANALYZING."""
        from app.tasks.audit import analyze_pages

        # Create a page
        page = CrawledPage(
            audit_run_id=test_audit_run.id,
            url="https://example.com",
            final_url="https://example.com",
            depth=0,
            status_code=200,
            title="Test Page",
            word_count=500,
            h1_count=1,
            crawled_at=datetime.now(timezone.utc),
        )
        db.add(page)
        db.commit()

        # Setup mocks
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_page.return_value = []

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.get_duplicate_title_issues.return_value = []

        result = analyze_pages(
            {"pages_rendered": 0},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        db.refresh(test_audit_run)
        assert test_audit_run.status == AuditStatus.ANALYZING

    @patch("app.tasks.audit.IssueAnalyzer")
    @patch("app.tasks.audit.DuplicateDetector")
    def test_analyze_pages_creates_issue_records(
        self,
        mock_detector_class,
        mock_analyzer_class,
        db: Session,
        test_audit_run: AuditRun,
        test_project: Project,
    ):
        """The analyze_pages task should create AuditIssue records."""
        from app.services.audit.analyzer import DetectedIssue
        from app.tasks.audit import analyze_pages

        # Create a page
        page = CrawledPage(
            audit_run_id=test_audit_run.id,
            url="https://example.com",
            final_url="https://example.com",
            depth=0,
            status_code=200,
            title="",  # Missing title
            word_count=500,
            h1_count=1,
            crawled_at=datetime.now(timezone.utc),
        )
        db.add(page)
        db.commit()

        # Setup analyzer to return issues
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_page.return_value = [
            DetectedIssue(
                page_url="https://example.com",
                issue_type=IssueType.MISSING_TITLE,
                severity=IssueSeverity.HIGH,
                details={},
            )
        ]

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.get_duplicate_title_issues.return_value = []

        result = analyze_pages(
            {"pages_rendered": 0},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        # Verify issues were created
        statement = select(AuditIssue).where(
            AuditIssue.audit_run_id == test_audit_run.id
        )
        issues = db.exec(statement).all()
        assert len(issues) >= 1
        assert issues[0].issue_type == IssueType.MISSING_TITLE

    @patch("app.tasks.audit.IssueAnalyzer")
    @patch("app.tasks.audit.DuplicateDetector")
    def test_analyze_pages_returns_issue_counts(
        self,
        mock_detector_class,
        mock_analyzer_class,
        db: Session,
        test_audit_run: AuditRun,
        test_project: Project,
    ):
        """The analyze_pages task should return issue counts by severity."""
        from app.services.audit.analyzer import DetectedIssue
        from app.tasks.audit import analyze_pages

        # Create a page
        page = CrawledPage(
            audit_run_id=test_audit_run.id,
            url="https://example.com",
            final_url="https://example.com",
            depth=0,
            status_code=200,
            title="",
            word_count=500,
            h1_count=1,
            crawled_at=datetime.now(timezone.utc),
        )
        db.add(page)
        db.commit()

        # Setup analyzer
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_page.return_value = [
            DetectedIssue(
                page_url="https://example.com",
                issue_type=IssueType.MISSING_TITLE,
                severity=IssueSeverity.HIGH,
                details={},
            )
        ]

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.get_duplicate_title_issues.return_value = []

        result = analyze_pages(
            {"pages_rendered": 0},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        assert "issues_by_severity" in result
        assert result["issues_by_severity"]["high"] >= 1


class TestComputeDiffTask:
    """Test the compute_diff task."""

    @patch("app.tasks.audit.AuditDiffer")
    def test_compute_diff_updates_status_to_diffing(
        self, mock_differ_class, db: Session, test_audit_run: AuditRun
    ):
        """The compute_diff task should update status to DIFFING."""
        from app.tasks.audit import compute_diff

        # Setup mock
        mock_differ = MagicMock()
        mock_differ_class.return_value = mock_differ
        mock_differ.get_previous_run.return_value = None
        mock_differ.compute_diff.return_value = MagicMock(
            new_issues=0, resolved_issues=0, unchanged_issues=0
        )

        result = compute_diff(
            {"issues_by_severity": {}},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        db.refresh(test_audit_run)
        # Should be COMPLETED after diff
        assert test_audit_run.status == AuditStatus.COMPLETED
        assert test_audit_run.finished_at is not None

    @patch("app.tasks.audit.AuditDiffer")
    def test_compute_diff_updates_project_last_audit_at(
        self,
        mock_differ_class,
        db: Session,
        test_audit_run: AuditRun,
        test_project: Project,
    ):
        """The compute_diff task should update project.last_audit_at."""
        from app.tasks.audit import compute_diff

        # Setup mock
        mock_differ = MagicMock()
        mock_differ_class.return_value = mock_differ
        mock_differ.get_previous_run.return_value = None
        mock_differ.compute_diff.return_value = MagicMock(
            new_issues=0, resolved_issues=0, unchanged_issues=0
        )

        result = compute_diff(
            {"issues_by_severity": {}},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        db.refresh(test_project)
        assert test_project.last_audit_at is not None

    @patch("app.tasks.audit.AuditDiffer")
    def test_compute_diff_returns_diff_counts(
        self, mock_differ_class, db: Session, test_audit_run: AuditRun
    ):
        """The compute_diff task should return diff counts."""
        from app.tasks.audit import compute_diff

        # Setup mock
        mock_differ = MagicMock()
        mock_differ_class.return_value = mock_differ
        mock_differ.get_previous_run.return_value = None
        mock_differ.compute_diff.return_value = MagicMock(
            new_issues=5, resolved_issues=2, unchanged_issues=3
        )

        result = compute_diff(
            {"issues_by_severity": {}},
            str(test_audit_run.project_id),
            str(test_audit_run.id),
        )

        assert result["new_issues"] == 5
        assert result["resolved_issues"] == 2
        assert result["unchanged_issues"] == 3


class TestRunAuditTask:
    """Test the run_audit orchestrator task."""

    @patch("app.tasks.audit.chain")
    def test_run_audit_creates_task_chain(self, mock_chain, db: Session):
        """The run_audit task should create a Celery chain."""
        from app.tasks.audit import run_audit

        project_id = str(uuid.uuid4())
        audit_run_id = str(uuid.uuid4())

        run_audit(project_id, audit_run_id)

        # Verify chain was called
        mock_chain.assert_called_once()
