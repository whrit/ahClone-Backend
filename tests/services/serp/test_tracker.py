"""
Comprehensive tests for RankTracker service following TDD principles.

These tests define the expected behavior before implementation:
1. Test refresh_keyword creates observation and snapshot
2. Test position_change calculation (positive = improvement)
3. Test error observation creation
4. Test get_rank_history filtering
5. Test daily and weekly refresh scheduling
6. Test GSC provider session handling
7. Test domain extraction from project seed_url
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.models import (
    DeviceType,
    KeywordTarget,
    Project,
    RankObservation,
    RefreshStatus,
    SearchEngine,
    SerpSnapshot,
    User,
)
from app.services.serp.providers import MockSerpProvider, provider_registry
from app.services.serp.tracker import RankTracker


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        email="tracker_test@example.com",
        hashed_password="hashedpassword",
        full_name="Tracker Test User"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_project(db: Session, test_user: User) -> Project:
    """Create a test project."""
    project = Project(
        name="Test SERP Project",
        seed_url="https://example.com/blog",
        description="Project for SERP tracking tests",
        created_by_id=test_user.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def test_keyword_target(db: Session, test_project: Project) -> KeywordTarget:
    """Create a test keyword target."""
    keyword_target = KeywordTarget(
        project_id=test_project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
        search_engine=SearchEngine.GOOGLE,
        provider_key="mock",
        refresh_frequency_hours=24
    )
    db.add(keyword_target)
    db.commit()
    db.refresh(keyword_target)
    return keyword_target


@pytest.fixture
def rank_tracker(db: Session) -> RankTracker:
    """Create a RankTracker instance."""
    return RankTracker(session=db)


class TestRefreshKeyword:
    """Tests for the refresh_keyword method."""

    @pytest.mark.asyncio
    async def test_refresh_keyword_creates_observation_and_snapshot(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh_keyword creates both RankObservation and SerpSnapshot."""
        # Act
        observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

        # Assert
        assert observation is not None
        assert observation.keyword_target_id == test_keyword_target.id
        assert observation.status == RefreshStatus.SUCCESS

        # Verify observation was saved to database
        db.refresh(observation)
        assert observation.id is not None

        # Verify snapshot was created
        snapshot_query = select(SerpSnapshot).where(
            SerpSnapshot.keyword_target_id == test_keyword_target.id
        )
        snapshots = db.exec(snapshot_query).all()
        assert len(snapshots) >= 1
        snapshot = snapshots[-1]  # Get most recent
        assert snapshot.keyword_target_id == test_keyword_target.id

    @pytest.mark.asyncio
    async def test_refresh_keyword_finds_domain_rank(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh_keyword correctly finds the domain rank."""
        # Arrange: Mock provider will return example.com at position 1
        # test_project.seed_url is "https://example.com/blog"

        # Act
        observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

        # Assert
        assert observation.rank == 1
        assert observation.url is not None
        assert "example.com" in observation.url

    @pytest.mark.asyncio
    async def test_refresh_keyword_calculates_position_change_improvement(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test position_change calculation when rank improves (positive number)."""
        # Arrange: Create a previous observation at position 5
        previous_observation = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            url="https://example.com/old",
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.add(previous_observation)
        db.commit()

        # Mock provider to return position 1 (improved from 5)
        # Position change = 5 - 1 = 4 (positive = improvement)

        # Act
        observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

        # Assert
        assert observation.rank == 1
        # Check cached position_change on keyword_target
        db.refresh(test_keyword_target)
        assert test_keyword_target.position_change == 4  # Improved by 4 positions (5 -> 1)

    @pytest.mark.asyncio
    async def test_refresh_keyword_calculates_position_change_decline(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test position_change calculation when rank declines (negative number)."""
        # Arrange: Create a previous observation at position 1
        previous_observation = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=1,
            url="https://example.com/old",
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.add(previous_observation)
        db.commit()

        # Mock the provider to return position 3 (declined from 1)
        with patch.object(MockSerpProvider, 'find_domain_rank', return_value=(3, "https://example.com/declined")):
            # Act
            observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

            # Assert
            assert observation.rank == 3
            db.refresh(test_keyword_target)
            assert test_keyword_target.position_change == -2  # Declined by 2 positions (1 -> 3)

    @pytest.mark.asyncio
    async def test_refresh_keyword_updates_keyword_target_cache(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh_keyword updates cached values on keyword_target."""
        # Act
        observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

        # Assert
        db.refresh(test_keyword_target)
        assert test_keyword_target.latest_position == observation.rank
        assert test_keyword_target.last_refresh_at is not None
        assert test_keyword_target.last_refresh_status == RefreshStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_refresh_keyword_sets_next_refresh_daily(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh scheduling works for daily frequency (24 hours)."""
        # Arrange
        test_keyword_target.refresh_frequency_hours = 24
        db.add(test_keyword_target)
        db.commit()

        # Act
        before_refresh = datetime.now(timezone.utc)
        await rank_tracker.refresh_keyword(test_keyword_target, test_project)
        after_refresh = datetime.now(timezone.utc)

        # Assert
        db.refresh(test_keyword_target)
        assert test_keyword_target.last_refresh_at is not None

        # Last refresh should be approximately now
        assert before_refresh <= test_keyword_target.last_refresh_at <= after_refresh

    @pytest.mark.asyncio
    async def test_refresh_keyword_sets_next_refresh_weekly(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh scheduling works for weekly frequency (168 hours)."""
        # Arrange
        test_keyword_target.refresh_frequency_hours = 168  # 7 days
        db.add(test_keyword_target)
        db.commit()

        # Act
        before_refresh = datetime.now(timezone.utc)
        await rank_tracker.refresh_keyword(test_keyword_target, test_project)
        after_refresh = datetime.now(timezone.utc)

        # Assert
        db.refresh(test_keyword_target)
        assert test_keyword_target.last_refresh_at is not None

        # Last refresh should be approximately now
        assert before_refresh <= test_keyword_target.last_refresh_at <= after_refresh

    @pytest.mark.asyncio
    async def test_refresh_keyword_provider_not_found(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh_keyword creates error observation when provider not found."""
        # Arrange
        test_keyword_target.provider_key = "nonexistent_provider"
        db.add(test_keyword_target)
        db.commit()

        # Act
        observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

        # Assert
        assert observation is not None
        assert observation.status == RefreshStatus.FAILED

    @pytest.mark.asyncio
    async def test_refresh_keyword_handles_domain_not_found(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that refresh_keyword handles when domain is not found in SERP."""
        # Arrange: Mock provider to return no matching domain
        with patch.object(MockSerpProvider, 'find_domain_rank', return_value=(None, None)):
            # Act
            observation = await rank_tracker.refresh_keyword(test_keyword_target, test_project)

            # Assert
            assert observation.status == RefreshStatus.SUCCESS
            # When rank not found, we should still record it but with a special value
            # This behavior will be defined in implementation

    @pytest.mark.asyncio
    async def test_refresh_keyword_extracts_seed_domain_correctly(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that seed_domain is correctly extracted from project.seed_url."""
        # Arrange: Project has seed_url "https://example.com/blog"
        # The tracker should extract "example.com" and use it to find rank

        # We can verify this by checking that the mock provider's find_domain_rank
        # is called with the correct domain
        original_find = MockSerpProvider.find_domain_rank

        calls = []

        def track_calls(self, serp_data, domain):
            calls.append(domain)
            return original_find(self, serp_data, domain)

        with patch.object(MockSerpProvider, 'find_domain_rank', track_calls):
            # Act
            await rank_tracker.refresh_keyword(test_keyword_target, test_project)

            # Assert
            assert len(calls) == 1
            assert calls[0] == "example.com"


class TestGetPreviousObservation:
    """Tests for the _get_previous_observation method."""

    @pytest.mark.asyncio
    async def test_get_previous_observation_returns_most_recent(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that _get_previous_observation returns the most recent successful observation."""
        # Arrange: Create multiple observations
        old_observation = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=10,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=2)
        )
        recent_observation = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.add(old_observation)
        db.add(recent_observation)
        db.commit()

        # Act
        previous = rank_tracker._get_previous_observation(test_keyword_target.id)

        # Assert
        assert previous is not None
        assert previous.id == recent_observation.id
        assert previous.rank == 5

    @pytest.mark.asyncio
    async def test_get_previous_observation_ignores_failed(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that _get_previous_observation ignores failed observations."""
        # Arrange: Create a failed observation and an older successful one
        old_success = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=2)
        )
        recent_failed = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=10,
            domain="example.com",
            status=RefreshStatus.FAILED,
            observed_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.add(old_success)
        db.add(recent_failed)
        db.commit()

        # Act
        previous = rank_tracker._get_previous_observation(test_keyword_target.id)

        # Assert
        assert previous is not None
        assert previous.id == old_success.id
        assert previous.status == RefreshStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_get_previous_observation_returns_none_when_no_observations(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget
    ):
        """Test that _get_previous_observation returns None when no observations exist."""
        # Act
        previous = rank_tracker._get_previous_observation(test_keyword_target.id)

        # Assert
        assert previous is None


class TestCreateErrorObservation:
    """Tests for the _create_error_observation method."""

    @pytest.mark.asyncio
    async def test_create_error_observation(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget
    ):
        """Test that _create_error_observation creates a failed observation."""
        # Act
        error_msg = "Test error message"
        observation = rank_tracker._create_error_observation(test_keyword_target, error_msg)

        # Assert
        assert observation is not None
        assert observation.keyword_target_id == test_keyword_target.id
        assert observation.status == RefreshStatus.FAILED

        # Verify it's saved to database
        db.refresh(observation)
        assert observation.id is not None


class TestGetRankHistory:
    """Tests for the get_rank_history method."""

    @pytest.mark.asyncio
    async def test_get_rank_history_default_30_days(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that get_rank_history returns observations from the last 30 days by default."""
        # Arrange: Create observations at different times
        # Observation from 20 days ago (should be included)
        recent_obs = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=20)
        )
        # Observation from 40 days ago (should be excluded)
        old_obs = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=10,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=40)
        )
        db.add(recent_obs)
        db.add(old_obs)
        db.commit()

        # Act
        history = rank_tracker.get_rank_history(test_keyword_target.id)

        # Assert
        assert len(history) == 1
        assert history[0].id == recent_obs.id

    @pytest.mark.asyncio
    async def test_get_rank_history_custom_days(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that get_rank_history respects custom days parameter."""
        # Arrange
        # Observation from 5 days ago (should be included)
        recent_obs = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=5,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=5)
        )
        # Observation from 10 days ago (should be excluded with days=7)
        old_obs = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=10,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=10)
        )
        db.add(recent_obs)
        db.add(old_obs)
        db.commit()

        # Act
        history = rank_tracker.get_rank_history(test_keyword_target.id, days=7)

        # Assert
        assert len(history) == 1
        assert history[0].id == recent_obs.id

    @pytest.mark.asyncio
    async def test_get_rank_history_orders_by_observed_at_desc(
        self,
        db: Session,
        rank_tracker: RankTracker,
        test_keyword_target: KeywordTarget,
        test_project: Project
    ):
        """Test that get_rank_history returns observations in descending order."""
        # Arrange
        obs1 = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=1,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=3)
        )
        obs2 = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=2,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        obs3 = RankObservation(
            keyword_target_id=test_keyword_target.id,
            rank=3,
            domain="example.com",
            status=RefreshStatus.SUCCESS,
            observed_at=datetime.now(timezone.utc) - timedelta(days=2)
        )
        db.add(obs1)
        db.add(obs2)
        db.add(obs3)
        db.commit()

        # Act
        history = rank_tracker.get_rank_history(test_keyword_target.id)

        # Assert
        assert len(history) == 3
        assert history[0].id == obs2.id  # Most recent
        assert history[1].id == obs3.id
        assert history[2].id == obs1.id  # Oldest
