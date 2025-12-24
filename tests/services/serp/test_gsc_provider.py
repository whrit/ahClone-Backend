"""
Tests for GSC-based SERP provider.

Tests the GSCBasedProvider implementation including:
- Successful data retrieval from mocked GSC data
- NOT_FOUND status when no data exists
- ERROR status when required parameters are missing
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.gsc import GSCQueryDaily
from app.services.serp.gsc_provider import GSCBasedProvider
from app.services.serp.providers import provider_registry as _registry


@pytest.fixture
def session():  # type: ignore[misc]
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def project_id() -> str:
    """Generate a test project ID."""
    return str(uuid.uuid4())


@pytest.fixture
def gsc_sample_data(session: Session, project_id: str):  # type: ignore[misc]
    """Create sample GSC data for testing."""
    today = date.today()
    project_uuid = uuid.UUID(project_id)

    # Create sample data across the expected date range (days 3-10 ago)
    test_data = [
        # Page 1: Best position, multiple days
        GSCQueryDaily(
            project_id=project_uuid,
            query="test keyword",
            page="https://example.com/page1",
            date=today - timedelta(days=5),
            clicks=10,
            impressions=100,
            position=2.5,
            ctr=0.1,
        ),
        GSCQueryDaily(
            project_id=project_uuid,
            query="test keyword",
            page="https://example.com/page1",
            date=today - timedelta(days=7),
            clicks=15,
            impressions=120,
            position=2.0,
            ctr=0.125,
        ),
        # Page 2: Worse position
        GSCQueryDaily(
            project_id=project_uuid,
            query="test keyword",
            page="https://example.com/page2",
            date=today - timedelta(days=6),
            clicks=5,
            impressions=80,
            position=5.5,
            ctr=0.0625,
        ),
        # Page 3: Different keyword (should not appear in results)
        GSCQueryDaily(
            project_id=project_uuid,
            query="different keyword",
            page="https://example.com/page3",
            date=today - timedelta(days=5),
            clicks=20,
            impressions=200,
            position=1.0,
            ctr=0.1,
        ),
    ]

    for record in test_data:
        session.add(record)
    session.commit()

    return test_data


@pytest.mark.asyncio
async def test_fetch_serp_success(session: Session, project_id: str, gsc_sample_data) -> None:  # noqa: ARG001
    """Test successful SERP data retrieval from GSC data."""
    _ = gsc_sample_data  # Fixture sets up test data
    provider = GSCBasedProvider(session=session)

    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=project_id,
    )

    # Verify response structure
    assert "organic" in result
    assert "total_results" in result
    assert "error" not in result
    assert result["total_results"] == 2

    # Verify results are ordered by position (best first)
    organic = result["organic"]
    assert len(organic) == 2
    assert organic[0]["url"] == "https://example.com/page1"
    assert organic[1]["url"] == "https://example.com/page2"

    # Verify first result (page1)
    result1 = organic[0]
    assert result1["position"] == 1
    assert result1["domain"] == "example.com"
    assert result1["title"] is None  # GSC doesn't provide title
    assert result1["description"] is None  # GSC doesn't provide description
    assert result1["avg_position"] == 2.25  # Average of 2.5 and 2.0
    assert result1["clicks"] == 25  # 10 + 15
    assert result1["impressions"] == 220  # 100 + 120

    # Verify second result (page2)
    result2 = organic[1]
    assert result2["position"] == 2
    assert result2["domain"] == "example.com"
    assert result2["avg_position"] == 5.5
    assert result2["clicks"] == 5
    assert result2["impressions"] == 80


@pytest.mark.asyncio
async def test_fetch_serp_not_found(session: Session, project_id: str, gsc_sample_data) -> None:  # noqa: ARG001
    """Test NOT_FOUND status when no data exists for keyword."""
    _ = gsc_sample_data  # Fixture sets up test data
    provider = GSCBasedProvider(session=session)

    result = await provider.fetch_serp(
        keyword="nonexistent keyword",
        project_id=project_id,
    )

    assert result["organic"] == []
    assert result["total_results"] == 0
    assert "error" not in result


@pytest.mark.asyncio
async def test_fetch_serp_different_project(session: Session, project_id: str, gsc_sample_data) -> None:  # noqa: ARG001
    """Test that data is properly isolated by project_id."""
    _ = (project_id, gsc_sample_data)  # Fixtures set up test data
    provider = GSCBasedProvider(session=session)
    different_project_id = str(uuid.uuid4())

    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=different_project_id,
    )

    assert result["organic"] == []
    assert result["total_results"] == 0


@pytest.mark.asyncio
async def test_fetch_serp_no_session() -> None:
    """Test ERROR status when session is not provided."""
    provider = GSCBasedProvider(session=None)

    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=str(uuid.uuid4()),
    )

    assert "error" in result
    assert "session is required" in result["error"].lower()
    assert result["organic"] == []


@pytest.mark.asyncio
async def test_fetch_serp_no_project_id(session: Session) -> None:
    """Test ERROR status when project_id is not provided."""
    provider = GSCBasedProvider(session=session)

    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=None,
    )

    assert "error" in result
    assert "project_id is required" in result["error"].lower()
    assert result["organic"] == []


@pytest.mark.asyncio
async def test_fetch_serp_invalid_project_id(session: Session) -> None:
    """Test ERROR status when project_id is invalid UUID."""
    provider = GSCBasedProvider(session=session)

    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id="invalid-uuid",
    )

    assert "error" in result
    assert "invalid project_id" in result["error"].lower()
    assert result["organic"] == []


@pytest.mark.asyncio
async def test_fetch_serp_date_range(session: Session, project_id: str) -> None:
    """Test that only data within the date range (days 3-10) is included."""
    today = date.today()
    project_uuid = uuid.UUID(project_id)

    # Create data outside the expected range
    recent_data = GSCQueryDaily(
        project_id=project_uuid,
        query="test keyword",
        page="https://example.com/recent",
        date=today - timedelta(days=1),  # Too recent
        clicks=100,
        impressions=1000,
        position=1.0,
        ctr=0.1,
    )

    old_data = GSCQueryDaily(
        project_id=project_uuid,
        query="test keyword",
        page="https://example.com/old",
        date=today - timedelta(days=15),  # Too old
        clicks=100,
        impressions=1000,
        position=1.0,
        ctr=0.1,
    )

    valid_data = GSCQueryDaily(
        project_id=project_uuid,
        query="test keyword",
        page="https://example.com/valid",
        date=today - timedelta(days=5),  # Within range
        clicks=50,
        impressions=500,
        position=3.0,
        ctr=0.1,
    )

    session.add(recent_data)
    session.add(old_data)
    session.add(valid_data)
    session.commit()

    provider = GSCBasedProvider(session=session)
    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=project_id,
    )

    assert len(result["organic"]) == 1
    assert result["organic"][0]["url"] == "https://example.com/valid"


@pytest.mark.asyncio
async def test_fetch_serp_handles_null_page(session: Session, project_id: str) -> None:
    """Test that records with null page are excluded."""
    today = date.today()
    project_uuid = uuid.UUID(project_id)

    # Create data with null page
    null_page_data = GSCQueryDaily(
        project_id=project_uuid,
        query="test keyword",
        page=None,
        date=today - timedelta(days=5),
        clicks=100,
        impressions=1000,
        position=1.0,
        ctr=0.1,
    )

    valid_data = GSCQueryDaily(
        project_id=project_uuid,
        query="test keyword",
        page="https://example.com/valid",
        date=today - timedelta(days=5),
        clicks=50,
        impressions=500,
        position=3.0,
        ctr=0.1,
    )

    session.add(null_page_data)
    session.add(valid_data)
    session.commit()

    provider = GSCBasedProvider(session=session)
    result = await provider.fetch_serp(
        keyword="test keyword",
        project_id=project_id,
    )

    assert len(result["organic"]) == 1
    assert result["organic"][0]["url"] == "https://example.com/valid"


def test_find_domain_rank(session: Session) -> None:
    """Test find_domain_rank method."""
    provider = GSCBasedProvider(session=session)

    serp_data = {
        "organic": [
            {"position": 1, "url": "https://example.com/page1", "domain": "example.com"},
            {"position": 2, "url": "https://test.com/page1", "domain": "test.com"},
            {"position": 3, "url": "https://sub.example.com/page2", "domain": "sub.example.com"},
        ],
        "total_results": 3,
    }

    # Test exact match
    position, url = provider.find_domain_rank(serp_data, "example.com")
    assert position == 1
    assert url == "https://example.com/page1"

    # Test subdomain match
    position, url = provider.find_domain_rank(serp_data, "example.com")
    assert position == 1  # Should match first occurrence

    # Test no match
    position, url = provider.find_domain_rank(serp_data, "nonexistent.com")
    assert position is None
    assert url is None


def test_provider_registration() -> None:
    """Test that GSCBasedProvider is properly registered."""
    provider_class = _registry.get("gsc_based")
    assert provider_class is not None
    assert provider_class == GSCBasedProvider
