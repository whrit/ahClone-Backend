"""
Test suite for SERP Celery tasks.
Following TDD approach - tests written first.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlmodel import Session, delete, select

import app.tasks.serp  # noqa: F401 - Import to register tasks
from app.core.celery import celery_app
from app.crud import create_user
from app.models import User, UserCreate
from app.models.project import Project
from app.models.serp import KeywordTarget, RankObservation, RefreshStatus, SerpSnapshot


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user for SERP tasks."""
    user = create_user(
        session=db,
        user_create=UserCreate(
            email=f"test-serp-{uuid.uuid4()}@example.com",
            password="test_password",
            is_superuser=False,
        ),
    )
    return user


@pytest.fixture
def test_project(db: Session, test_user: User) -> Project:
    """Create a test project for SERP tasks."""
    project = Project(
        id=uuid.uuid4(),
        name="Test SERP Project",
        seed_url="https://example.com",
        description="Test project for SERP tracking",
        created_by_id=test_user.id,
        settings={},
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def test_keyword_target(db: Session, test_project: Project) -> KeywordTarget:
    """Create a test keyword target."""
    keyword_target = KeywordTarget(
        id=uuid.uuid4(),
        project_id=test_project.id,
        keyword="test keyword",
        locale="en-US",
        device="desktop",
        search_engine="google",
        provider_key="serpapi",
        refresh_frequency_hours=24,
        is_active=True,
    )
    db.add(keyword_target)
    db.commit()
    db.refresh(keyword_target)
    return keyword_target


class TestTaskRegistration:
    """Test that SERP tasks are properly registered with Celery."""

    def test_refresh_keyword_task_is_registered(self):
        """The refresh_keyword task should be registered."""
        assert "app.tasks.serp.refresh_keyword" in celery_app.tasks

    def test_refresh_project_keywords_task_is_registered(self):
        """The refresh_project_keywords task should be registered."""
        assert "app.tasks.serp.refresh_project_keywords" in celery_app.tasks

    def test_refresh_all_due_keywords_task_is_registered(self):
        """The refresh_all_due_keywords task should be registered."""
        assert "app.tasks.serp.refresh_all_due_keywords" in celery_app.tasks


class TestRefreshKeywordTask:
    """Test the refresh_keyword task."""

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_keyword_gets_keyword_target_and_project(
        self, mock_tracker_class, db: Session, test_keyword_target: KeywordTarget, test_project: Project
    ):
        """The refresh_keyword task should retrieve KeywordTarget and Project from database."""
        from app.tasks.serp import refresh_keyword

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                keyword_target_id=test_keyword_target.id,
                rank=5,
                status=RefreshStatus.SUCCESS,
                url="https://example.com/page",
            )
        )

        # Run task
        result = refresh_keyword(str(test_keyword_target.id))

        # Verify tracker was created with session
        mock_tracker_class.assert_called_once()
        # Verify refresh_keyword was called with correct arguments
        mock_tracker.refresh_keyword.assert_called_once()

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_keyword_runs_tracker_with_asyncio(
        self, mock_tracker_class, db: Session, test_keyword_target: KeywordTarget
    ):
        """The refresh_keyword task should run tracker.refresh_keyword() using asyncio.run()."""
        from app.tasks.serp import refresh_keyword

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_observation = MagicMock(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            status=RefreshStatus.SUCCESS,
            url="https://example.com/page",
        )
        mock_tracker.refresh_keyword = AsyncMock(return_value=mock_observation)

        # Run task
        result = refresh_keyword(str(test_keyword_target.id))

        # Verify async method was called
        mock_tracker.refresh_keyword.assert_called_once()

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_keyword_returns_result_dict(
        self, mock_tracker_class, db: Session, test_keyword_target: KeywordTarget
    ):
        """The refresh_keyword task should return dict with keyword, rank, status."""
        from app.tasks.serp import refresh_keyword

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_observation = MagicMock(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            status=RefreshStatus.SUCCESS,
            url="https://example.com/page",
        )
        mock_tracker.refresh_keyword = AsyncMock(return_value=mock_observation)

        # Run task
        result = refresh_keyword(str(test_keyword_target.id))

        # Verify result structure
        assert isinstance(result, dict)
        assert "keyword" in result
        assert "rank" in result
        assert "status" in result
        assert result["keyword"] == "test keyword"
        assert result["rank"] == 5
        assert result["status"] == RefreshStatus.SUCCESS

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_keyword_handles_errors_gracefully(
        self, mock_tracker_class, db: Session, test_keyword_target: KeywordTarget
    ):
        """The refresh_keyword task should handle errors gracefully without crashing."""
        from app.tasks.serp import refresh_keyword

        # Setup mock to raise exception
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(side_effect=Exception("Test error"))

        # Run task - should not raise, should return error status
        result = refresh_keyword(str(test_keyword_target.id))

        # Verify error is handled
        assert isinstance(result, dict)
        assert result["status"] == RefreshStatus.FAILED
        assert "error" in result

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_keyword_handles_missing_keyword_target(
        self, mock_tracker_class, db: Session
    ):
        """The refresh_keyword task should handle missing KeywordTarget gracefully."""
        from app.tasks.serp import refresh_keyword

        # Run task with non-existent ID
        result = refresh_keyword(str(uuid.uuid4()))

        # Verify error is handled
        assert isinstance(result, dict)
        assert result["status"] == RefreshStatus.FAILED
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestRefreshProjectKeywordsTask:
    """Test the refresh_project_keywords task."""

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_gets_project(
        self, mock_tracker_class, db: Session, test_project: Project
    ):
        """The refresh_project_keywords task should retrieve Project from database."""
        from app.tasks.serp import refresh_project_keywords

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                rank=5, status=RefreshStatus.SUCCESS, url="https://example.com"
            )
        )

        # Run task
        result = refresh_project_keywords(str(test_project.id))

        # Should complete without error
        assert isinstance(result, dict)

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_queries_due_keywords(
        self, mock_tracker_class, db: Session, test_project: Project
    ):
        """The refresh_project_keywords task should query due KeywordTarget records."""
        from app.tasks.serp import refresh_project_keywords

        # Create keywords with different states
        # Due keyword (active, past next_refresh_at)
        due_keyword = KeywordTarget(
            id=uuid.uuid4(),
            project_id=test_project.id,
            keyword="due keyword",
            locale="en-US",
            is_active=True,
            last_refresh_at=datetime.now(timezone.utc) - timedelta(hours=25),
            refresh_frequency_hours=24,
        )
        db.add(due_keyword)

        # Not due keyword (active, future next_refresh_at)
        not_due_keyword = KeywordTarget(
            id=uuid.uuid4(),
            project_id=test_project.id,
            keyword="not due keyword",
            locale="en-US",
            is_active=True,
            last_refresh_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_frequency_hours=24,
        )
        db.add(not_due_keyword)

        # Inactive keyword
        inactive_keyword = KeywordTarget(
            id=uuid.uuid4(),
            project_id=test_project.id,
            keyword="inactive keyword",
            locale="en-US",
            is_active=False,
        )
        db.add(inactive_keyword)

        # Never refreshed keyword (should be due)
        never_refreshed = KeywordTarget(
            id=uuid.uuid4(),
            project_id=test_project.id,
            keyword="never refreshed",
            locale="en-US",
            is_active=True,
            last_refresh_at=None,
        )
        db.add(never_refreshed)

        db.commit()

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                rank=5, status=RefreshStatus.SUCCESS, url="https://example.com"
            )
        )

        # Run task
        result = refresh_project_keywords(str(test_project.id))

        # Verify correct keywords were refreshed
        # Should refresh: due_keyword and never_refreshed (2 total)
        assert result["refreshed_count"] == 2

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_respects_daily_cap(
        self, mock_tracker_class, db: Session, test_project: Project
    ):
        """The refresh_project_keywords task should respect SERP_REFRESH_DAILY_CAP."""
        from app.core.config import settings
        from app.tasks.serp import refresh_project_keywords

        # Create more keywords than daily cap
        for i in range(settings.SERP_REFRESH_DAILY_CAP + 10):
            keyword = KeywordTarget(
                id=uuid.uuid4(),
                project_id=test_project.id,
                keyword=f"keyword {i}",
                locale="en-US",
                is_active=True,
                last_refresh_at=None,  # All are due
            )
            db.add(keyword)
        db.commit()

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                rank=5, status=RefreshStatus.SUCCESS, url="https://example.com"
            )
        )

        # Run task
        result = refresh_project_keywords(str(test_project.id))

        # Verify daily cap was respected
        assert result["refreshed_count"] <= settings.SERP_REFRESH_DAILY_CAP

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_updates_project_timestamp(
        self, mock_tracker_class, db: Session, test_project: Project, test_keyword_target: KeywordTarget
    ):
        """The refresh_project_keywords task should update project.last_serp_refresh_at."""
        from app.tasks.serp import refresh_project_keywords

        # Make keyword due
        test_keyword_target.is_active = True
        test_keyword_target.last_refresh_at = None
        db.add(test_keyword_target)
        db.commit()

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                rank=5, status=RefreshStatus.SUCCESS, url="https://example.com"
            )
        )

        # Verify timestamp is None before
        assert test_project.last_serp_refresh_at is None

        # Run task
        result = refresh_project_keywords(str(test_project.id))

        # Verify timestamp was updated
        db.refresh(test_project)
        assert test_project.last_serp_refresh_at is not None

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_returns_result_dict(
        self, mock_tracker_class, db: Session, test_project: Project, test_keyword_target: KeywordTarget
    ):
        """The refresh_project_keywords task should return dict with refreshed count and results."""
        from app.tasks.serp import refresh_project_keywords

        # Make keyword due
        test_keyword_target.is_active = True
        test_keyword_target.last_refresh_at = None
        db.add(test_keyword_target)
        db.commit()

        # Setup mock
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker
        mock_tracker.refresh_keyword = AsyncMock(
            return_value=MagicMock(
                rank=5, status=RefreshStatus.SUCCESS, url="https://example.com"
            )
        )

        # Run task
        result = refresh_project_keywords(str(test_project.id))

        # Verify result structure
        assert isinstance(result, dict)
        assert "refreshed_count" in result
        assert "results" in result
        assert result["refreshed_count"] == 1

    @patch("app.tasks.serp.RankTracker")
    def test_refresh_project_keywords_handles_missing_project(
        self, mock_tracker_class, db: Session
    ):
        """The refresh_project_keywords task should handle missing Project gracefully."""
        from app.tasks.serp import refresh_project_keywords

        # Run task with non-existent ID
        result = refresh_project_keywords(str(uuid.uuid4()))

        # Verify error is handled
        assert isinstance(result, dict)
        assert "error" in result


class TestRefreshAllDueKeywordsTask:
    """Test the refresh_all_due_keywords task."""

    @pytest.fixture(autouse=True)
    def cleanup_keywords(self, db: Session):
        """Clean up all keyword targets before each test to ensure isolation."""
        # Delete in order to respect foreign key constraints
        db.execute(delete(RankObservation))
        db.execute(delete(SerpSnapshot))
        db.execute(delete(KeywordTarget))
        db.commit()
        yield
        # Cleanup after test as well
        db.execute(delete(RankObservation))
        db.execute(delete(SerpSnapshot))
        db.execute(delete(KeywordTarget))
        db.commit()

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_queries_all_projects(
        self, mock_refresh_task, db: Session, test_user: User
    ):
        """The refresh_all_due_keywords task should query all projects with due keywords."""
        from app.tasks.serp import refresh_all_due_keywords

        # Create multiple projects with due keywords
        project1 = Project(
            id=uuid.uuid4(),
            name="Project 1",
            seed_url="https://example1.com",
            created_by_id=test_user.id,
        )
        project2 = Project(
            id=uuid.uuid4(),
            name="Project 2",
            seed_url="https://example2.com",
            created_by_id=test_user.id,
        )
        db.add(project1)
        db.add(project2)
        db.commit()

        # Add due keywords to both projects
        keyword1 = KeywordTarget(
            project_id=project1.id,
            keyword="keyword 1",
            locale="en-US",
            is_active=True,
            last_refresh_at=None,
        )
        keyword2 = KeywordTarget(
            project_id=project2.id,
            keyword="keyword 2",
            locale="en-US",
            is_active=True,
            last_refresh_at=None,
        )
        db.add(keyword1)
        db.add(keyword2)
        db.commit()

        # Setup mock to return success
        mock_refresh_task.delay.return_value = MagicMock(id="task-id")

        # Run task
        result = refresh_all_due_keywords()

        # Verify both projects were queued
        assert result["projects_queued"] == 2
        assert mock_refresh_task.delay.call_count == 2

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_groups_by_project(
        self, mock_refresh_task, db: Session, test_user: User
    ):
        """The refresh_all_due_keywords task should group keywords by project_id."""
        from app.tasks.serp import refresh_all_due_keywords

        # Create project with multiple due keywords
        project = Project(
            id=uuid.uuid4(),
            name="Multi-keyword Project",
            seed_url="https://example.com",
            created_by_id=test_user.id,
        )
        db.add(project)
        db.commit()

        # Add multiple due keywords to same project
        for i in range(5):
            keyword = KeywordTarget(
                project_id=project.id,
                keyword=f"keyword {i}",
                locale="en-US",
                is_active=True,
                last_refresh_at=None,
            )
            db.add(keyword)
        db.commit()

        # Setup mock
        mock_refresh_task.delay.return_value = MagicMock(id="task-id")

        # Run task
        result = refresh_all_due_keywords()

        # Should queue only 1 task (for the project)
        assert result["projects_queued"] == 1
        assert result["total_keywords"] == 5
        mock_refresh_task.delay.assert_called_once_with(str(project.id))

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_queues_tasks(
        self, mock_refresh_task, db: Session, test_project: Project, test_keyword_target: KeywordTarget
    ):
        """The refresh_all_due_keywords task should queue refresh_project_keywords.delay() tasks."""
        from app.tasks.serp import refresh_all_due_keywords

        # Make keyword due
        test_keyword_target.is_active = True
        test_keyword_target.last_refresh_at = None
        db.add(test_keyword_target)
        db.commit()

        # Setup mock
        mock_refresh_task.delay.return_value = MagicMock(id="task-id")

        # Run task
        result = refresh_all_due_keywords()

        # Verify task was queued
        mock_refresh_task.delay.assert_called_once_with(str(test_project.id))

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_returns_result_dict(
        self, mock_refresh_task, db: Session, test_project: Project, test_keyword_target: KeywordTarget
    ):
        """The refresh_all_due_keywords task should return dict with projects_queued and total_keywords."""
        from app.tasks.serp import refresh_all_due_keywords

        # Make keyword due
        test_keyword_target.is_active = True
        test_keyword_target.last_refresh_at = None
        db.add(test_keyword_target)
        db.commit()

        # Setup mock
        mock_refresh_task.delay.return_value = MagicMock(id="task-id")

        # Run task
        result = refresh_all_due_keywords()

        # Verify result structure
        assert isinstance(result, dict)
        assert "projects_queued" in result
        assert "total_keywords" in result
        assert result["projects_queued"] == 1
        assert result["total_keywords"] == 1

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_skips_inactive_keywords(
        self, mock_refresh_task, db: Session, test_project: Project
    ):
        """The refresh_all_due_keywords task should skip inactive keywords."""
        from app.tasks.serp import refresh_all_due_keywords

        # Create only inactive keywords
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="inactive keyword",
            locale="en-US",
            is_active=False,
            last_refresh_at=None,
        )
        db.add(keyword)
        db.commit()

        # Run task
        result = refresh_all_due_keywords()

        # Should not queue any tasks
        assert result["projects_queued"] == 0
        assert result["total_keywords"] == 0
        mock_refresh_task.delay.assert_not_called()

    @patch("app.tasks.serp.refresh_project_keywords")
    def test_refresh_all_due_keywords_skips_not_due_keywords(
        self, mock_refresh_task, db: Session, test_project: Project
    ):
        """The refresh_all_due_keywords task should skip keywords not yet due."""
        from app.tasks.serp import refresh_all_due_keywords

        # Create keyword that was just refreshed
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="recently refreshed",
            locale="en-US",
            is_active=True,
            last_refresh_at=datetime.now(timezone.utc) - timedelta(hours=1),
            refresh_frequency_hours=24,
        )
        db.add(keyword)
        db.commit()

        # Run task
        result = refresh_all_due_keywords()

        # Should not queue any tasks
        assert result["projects_queued"] == 0
        assert result["total_keywords"] == 0
        mock_refresh_task.delay.assert_not_called()
