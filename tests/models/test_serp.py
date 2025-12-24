"""
Tests for SERP (Search Engine Results Page) models.

Following TDD approach:
1. Write failing tests first (RED)
2. Implement models to make tests pass (GREEN)
3. Refactor as needed (REFACTOR)
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, create_engine, select

# Import User and Project first to ensure they're registered before serp models
from app.models import User
from app.models.project import Project
from app.models.serp import (
    DeviceType,
    KeywordTarget,
    KeywordTargetCreate,
    KeywordTargetPublic,
    KeywordTargetsPublic,
    RankHistoryResponse,
    RankObservation,
    RankObservationPublic,
    RefreshStatus,
    SearchEngine,
    SerpResultPublic,
    SerpSnapshot,
    SerpSnapshotPublic,
)


@pytest.fixture(name="engine")
def engine_fixture():
    """Create an in-memory SQLite engine for testing."""
    from sqlmodel import SQLModel

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    """Create a database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="test_project")
def test_project_fixture(session):
    """Create a test project."""
    from app.models import User

    # Create test user
    user = User(
        email="test@example.com",
        hashed_password="hashedpassword",
        full_name="Test User"
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Create test project
    project = Project(
        name="Test Project",
        seed_url="https://example.com",
        created_by_id=user.id
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    return project


class TestEnums:
    """Test enum definitions."""

    def test_device_type_enum(self):
        """Test DeviceType enum values."""
        assert DeviceType.DESKTOP == "desktop"
        assert DeviceType.MOBILE == "mobile"
        assert DeviceType.TABLET == "tablet"

    def test_search_engine_enum(self):
        """Test SearchEngine enum values."""
        assert SearchEngine.GOOGLE == "google"
        assert SearchEngine.BING == "bing"

    def test_refresh_status_enum(self):
        """Test RefreshStatus enum values."""
        assert RefreshStatus.PENDING == "pending"
        assert RefreshStatus.SUCCESS == "success"
        assert RefreshStatus.FAILED == "failed"
        assert RefreshStatus.RATE_LIMITED == "rate_limited"


class TestKeywordTarget:
    """Test KeywordTarget model."""

    def test_create_keyword_target(self, session, test_project):
        """Test creating a keyword target."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="seo tools",
            locale="en-US",
            device=DeviceType.DESKTOP,
            search_engine=SearchEngine.GOOGLE,
            provider_key="serpapi",
            refresh_frequency_hours=24,
            latest_position=5,
            position_change=2
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        assert keyword.id is not None
        assert keyword.project_id == test_project.id
        assert keyword.keyword == "seo tools"
        assert keyword.locale == "en-US"
        assert keyword.device == DeviceType.DESKTOP
        assert keyword.search_engine == SearchEngine.GOOGLE
        assert keyword.provider_key == "serpapi"
        assert keyword.refresh_frequency_hours == 24
        assert keyword.latest_position == 5
        assert keyword.position_change == 2
        assert keyword.is_active is True
        assert keyword.created_at is not None
        assert keyword.updated_at is not None
        assert keyword.last_refresh_at is None

    def test_keyword_target_defaults(self, session, test_project):
        """Test KeywordTarget default values."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        assert keyword.device == DeviceType.DESKTOP
        assert keyword.search_engine == SearchEngine.GOOGLE
        assert keyword.provider_key == "serpapi"
        assert keyword.refresh_frequency_hours == 24
        assert keyword.is_active is True
        assert keyword.latest_position is None
        assert keyword.position_change is None
        assert keyword.last_refresh_at is None
        assert keyword.last_refresh_status is None

    def test_keyword_target_relationship(self, session, test_project):
        """Test that keyword targets are linked to project via foreign key."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        # Test the foreign key relationship
        assert keyword.project_id == test_project.id
        # Verify project exists
        assert test_project.id is not None
        assert test_project.name == "Test Project"

    def test_keyword_target_index(self, session, test_project):
        """Test that project_id is indexed."""
        # Create multiple keywords
        keywords = [
            KeywordTarget(
                project_id=test_project.id,
                keyword=f"keyword {i}",
                locale="en-US"
            )
            for i in range(3)
        ]
        for kw in keywords:
            session.add(kw)
        session.commit()

        # Query by project_id should be efficient
        statement = select(KeywordTarget).where(
            KeywordTarget.project_id == test_project.id
        )
        results = session.exec(statement).all()
        assert len(results) == 3


class TestRankObservation:
    """Test RankObservation model."""

    def test_create_rank_observation(self, session, test_project):
        """Test creating a rank observation."""
        # Create keyword target first
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="seo tools",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        # Create rank observation
        observation = RankObservation(
            keyword_target_id=keyword.id,
            observed_at=datetime.now(timezone.utc),
            rank=5,
            url="https://example.com/seo-tools",
            domain="example.com",
            title="Best SEO Tools 2024",
            snippet="Discover the top SEO tools for your business...",
            status=RefreshStatus.SUCCESS
        )
        session.add(observation)
        session.commit()
        session.refresh(observation)

        assert observation.id is not None
        assert observation.keyword_target_id == keyword.id
        assert observation.rank == 5
        assert observation.url == "https://example.com/seo-tools"
        assert observation.domain == "example.com"
        assert observation.title == "Best SEO Tools 2024"
        assert observation.snippet == "Discover the top SEO tools for your business..."
        assert observation.status == RefreshStatus.SUCCESS
        assert observation.observed_at is not None

    def test_rank_observation_defaults(self, session, test_project):
        """Test RankObservation default values."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        observation = RankObservation(
            keyword_target_id=keyword.id,
            observed_at=datetime.now(timezone.utc),
            rank=10
        )
        session.add(observation)
        session.commit()
        session.refresh(observation)

        assert observation.url is None
        assert observation.domain is None
        assert observation.title is None
        assert observation.snippet is None
        assert observation.status == RefreshStatus.PENDING

    def test_rank_observation_relationship(self, session, test_project):
        """Test relationship between RankObservation and KeywordTarget."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        observation = RankObservation(
            keyword_target_id=keyword.id,
            observed_at=datetime.now(timezone.utc),
            rank=3
        )
        session.add(observation)
        session.commit()
        session.refresh(observation)

        # Test the relationship
        assert observation.keyword_target is not None
        assert observation.keyword_target.id == keyword.id
        assert observation.keyword_target.keyword == "test keyword"

    def test_rank_observation_index(self, session, test_project):
        """Test that keyword_target_id and observed_at are indexed."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        # Create multiple observations
        observations = [
            RankObservation(
                keyword_target_id=keyword.id,
                observed_at=datetime.now(timezone.utc),
                rank=i + 1
            )
            for i in range(3)
        ]
        for obs in observations:
            session.add(obs)
        session.commit()

        # Query by keyword_target_id should be efficient
        statement = select(RankObservation).where(
            RankObservation.keyword_target_id == keyword.id
        )
        results = session.exec(statement).all()
        assert len(results) == 3


class TestSerpSnapshot:
    """Test SerpSnapshot model."""

    def test_create_serp_snapshot(self, session, test_project):
        """Test creating a SERP snapshot."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="seo tools",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=datetime.now(timezone.utc),
            results_json={
                "organic_results": [
                    {"position": 1, "url": "https://example.com", "title": "Example"},
                    {"position": 2, "url": "https://test.com", "title": "Test"}
                ]
            },
            total_results=1234567,
            raw_response={"search_metadata": {"status": "success"}}
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.keyword_target_id == keyword.id
        assert snapshot.results_json is not None
        assert "organic_results" in snapshot.results_json
        assert len(snapshot.results_json["organic_results"]) == 2
        assert snapshot.total_results == 1234567
        assert snapshot.raw_response is not None
        assert snapshot.captured_at is not None

    def test_serp_snapshot_defaults(self, session, test_project):
        """Test SerpSnapshot default values."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=datetime.now(timezone.utc),
            results_json={}
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert snapshot.total_results is None
        assert snapshot.raw_response is None

    def test_serp_snapshot_relationship(self, session, test_project):
        """Test relationship between SerpSnapshot and KeywordTarget."""
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=datetime.now(timezone.utc),
            results_json={"test": "data"}
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        # Test the relationship
        assert snapshot.keyword_target is not None
        assert snapshot.keyword_target.id == keyword.id
        assert snapshot.keyword_target.keyword == "test keyword"


class TestCascadeDelete:
    """Test cascade delete behavior."""

    def test_keyword_target_cascade_delete(self, session, test_project):
        """Test that deleting a KeywordTarget cascades to observations and snapshots."""
        # Create keyword target
        keyword = KeywordTarget(
            project_id=test_project.id,
            keyword="test keyword",
            locale="en-US"
        )
        session.add(keyword)
        session.commit()
        session.refresh(keyword)

        # Create observations
        observation = RankObservation(
            keyword_target_id=keyword.id,
            observed_at=datetime.now(timezone.utc),
            rank=5
        )
        session.add(observation)

        # Create snapshot
        snapshot = SerpSnapshot(
            keyword_target_id=keyword.id,
            captured_at=datetime.now(timezone.utc),
            results_json={"test": "data"}
        )
        session.add(snapshot)
        session.commit()

        # Delete keyword target
        session.delete(keyword)
        session.commit()

        # Verify observations and snapshots are deleted
        obs_statement = select(RankObservation).where(
            RankObservation.keyword_target_id == keyword.id
        )
        obs_results = session.exec(obs_statement).all()
        assert len(obs_results) == 0

        snap_statement = select(SerpSnapshot).where(
            SerpSnapshot.keyword_target_id == keyword.id
        )
        snap_results = session.exec(snap_statement).all()
        assert len(snap_results) == 0


class TestAPIModels:
    """Test API request/response models."""

    def test_keyword_target_create(self):
        """Test KeywordTargetCreate model."""
        create_data = KeywordTargetCreate(
            keyword="seo tools",
            locale="en-US",
            device=DeviceType.MOBILE,
            search_engine=SearchEngine.BING,
            provider_key="valueserp",
            refresh_frequency_hours=12
        )
        assert create_data.keyword == "seo tools"
        assert create_data.locale == "en-US"
        assert create_data.device == DeviceType.MOBILE
        assert create_data.search_engine == SearchEngine.BING
        assert create_data.provider_key == "valueserp"
        assert create_data.refresh_frequency_hours == 12

    def test_keyword_target_create_defaults(self):
        """Test KeywordTargetCreate default values."""
        create_data = KeywordTargetCreate(
            keyword="test",
            locale="en-US"
        )
        assert create_data.device == DeviceType.DESKTOP
        assert create_data.search_engine == SearchEngine.GOOGLE
        assert create_data.provider_key == "serpapi"
        assert create_data.refresh_frequency_hours == 24

    def test_keyword_target_public(self):
        """Test KeywordTargetPublic model."""
        public_data = KeywordTargetPublic(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            keyword="seo tools",
            locale="en-US",
            device=DeviceType.DESKTOP,
            search_engine=SearchEngine.GOOGLE,
            provider_key="serpapi",
            refresh_frequency_hours=24,
            is_active=True,
            latest_position=5,
            position_change=2,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_refresh_at=None,
            last_refresh_status=None
        )
        assert public_data.keyword == "seo tools"
        assert public_data.latest_position == 5

    def test_keyword_targets_public(self):
        """Test KeywordTargetsPublic model."""
        targets = [
            KeywordTargetPublic(
                id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                keyword=f"keyword {i}",
                locale="en-US",
                device=DeviceType.DESKTOP,
                search_engine=SearchEngine.GOOGLE,
                provider_key="serpapi",
                refresh_frequency_hours=24,
                is_active=True,
                latest_position=None,
                position_change=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                last_refresh_at=None,
                last_refresh_status=None
            )
            for i in range(2)
        ]
        response = KeywordTargetsPublic(data=targets, count=2)
        assert response.count == 2
        assert len(response.data) == 2

    def test_rank_observation_public(self):
        """Test RankObservationPublic model."""
        obs_public = RankObservationPublic(
            id=uuid.uuid4(),
            keyword_target_id=uuid.uuid4(),
            observed_at=datetime.now(timezone.utc),
            rank=5,
            url="https://example.com",
            domain="example.com",
            title="Example Page",
            snippet="This is an example...",
            status=RefreshStatus.SUCCESS
        )
        assert obs_public.rank == 5
        assert obs_public.url == "https://example.com"

    def test_rank_history_response(self):
        """Test RankHistoryResponse model."""
        observations = [
            RankObservationPublic(
                id=uuid.uuid4(),
                keyword_target_id=uuid.uuid4(),
                observed_at=datetime.now(timezone.utc),
                rank=i + 1,
                url=None,
                domain=None,
                title=None,
                snippet=None,
                status=RefreshStatus.SUCCESS
            )
            for i in range(3)
        ]
        response = RankHistoryResponse(data=observations, count=3)
        assert response.count == 3
        assert len(response.data) == 3

    def test_serp_result_public(self):
        """Test SerpResultPublic model."""
        result = SerpResultPublic(
            position=1,
            url="https://example.com",
            domain="example.com",
            title="Example Page",
            snippet="This is an example snippet...",
            displayed_url="example.com"
        )
        assert result.position == 1
        assert result.url == "https://example.com"

    def test_serp_snapshot_public(self):
        """Test SerpSnapshotPublic model."""
        snapshot = SerpSnapshotPublic(
            id=uuid.uuid4(),
            keyword_target_id=uuid.uuid4(),
            captured_at=datetime.now(timezone.utc),
            results=[
                SerpResultPublic(
                    position=1,
                    url="https://example.com",
                    domain="example.com",
                    title="Example",
                    snippet="snippet",
                    displayed_url="example.com"
                )
            ],
            total_results=1000000
        )
        assert len(snapshot.results) == 1
        assert snapshot.total_results == 1000000
