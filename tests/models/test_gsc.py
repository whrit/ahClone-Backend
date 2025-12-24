"""
Tests for GSC (Google Search Console) models.

Following TDD approach:
1. Write failing tests first
2. Implement models to make tests pass
3. Refactor as needed
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlmodel import Session, create_engine, select

from app.models.gsc import (
    ClusterPublic,
    GSCPageDaily,
    GSCPagesResponse,
    GSCProperty,
    GSCPropertyPublic,
    GSCQueriesResponse,
    GSCQueryDaily,
    GSCQueryRow,
    KeywordCluster,
    KeywordClusterMember,
    OpportunitiesResponse,
    OpportunityRow,
)
from app.models.project import Project, ProjectCreate


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


class TestGSCProperty:
    """Test GSCProperty model."""

    def test_create_gsc_property(self, session, test_project):
        """Test creating a GSC property."""
        gsc_prop = GSCProperty(
            project_id=test_project.id,
            site_url="sc-domain:example.com",
            permission_level="siteOwner",
            verified=True
        )
        session.add(gsc_prop)
        session.commit()
        session.refresh(gsc_prop)

        assert gsc_prop.id is not None
        assert gsc_prop.project_id == test_project.id
        assert gsc_prop.site_url == "sc-domain:example.com"
        assert gsc_prop.permission_level == "siteOwner"
        assert gsc_prop.verified is True
        assert gsc_prop.sync_status == "pending"
        assert gsc_prop.search_type == "web"
        assert gsc_prop.linked_at is not None
        assert gsc_prop.last_sync_at is None
        assert gsc_prop.sync_error is None

    def test_gsc_property_defaults(self, session, test_project):
        """Test GSC property default values."""
        gsc_prop = GSCProperty(
            project_id=test_project.id,
            site_url="https://example.com/"
        )
        session.add(gsc_prop)
        session.commit()
        session.refresh(gsc_prop)

        assert gsc_prop.verified is False
        assert gsc_prop.sync_status == "pending"
        assert gsc_prop.search_type == "web"
        assert gsc_prop.permission_level is None

    def test_gsc_property_unique_project(self, session, test_project):
        """Test that project_id is unique for GSC properties."""
        gsc_prop1 = GSCProperty(
            project_id=test_project.id,
            site_url="sc-domain:example.com"
        )
        session.add(gsc_prop1)
        session.commit()

        # Try to add another property for the same project
        gsc_prop2 = GSCProperty(
            project_id=test_project.id,
            site_url="https://example.com/"
        )
        session.add(gsc_prop2)

        with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
            session.commit()

    def test_gsc_property_relationship(self, session, test_project):
        """Test relationship between GSCProperty and Project."""
        gsc_prop = GSCProperty(
            project_id=test_project.id,
            site_url="sc-domain:example.com"
        )
        session.add(gsc_prop)
        session.commit()
        session.refresh(gsc_prop)

        # Test the relationship
        assert gsc_prop.project is not None
        assert gsc_prop.project.id == test_project.id
        assert gsc_prop.project.name == "Test Project"


class TestGSCQueryDaily:
    """Test GSCQueryDaily model."""

    def test_create_query_daily(self, session, test_project):
        """Test creating a GSC query daily record."""
        query_daily = GSCQueryDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            query="seo platform",
            page="https://example.com/seo-tools",
            country="USA",
            device="MOBILE",
            clicks=150,
            impressions=2000,
            ctr=0.075,
            position=5.2
        )
        session.add(query_daily)
        session.commit()
        session.refresh(query_daily)

        assert query_daily.id is not None
        assert query_daily.project_id == test_project.id
        assert query_daily.date == date(2024, 1, 15)
        assert query_daily.query == "seo platform"
        assert query_daily.page == "https://example.com/seo-tools"
        assert query_daily.country == "USA"
        assert query_daily.device == "MOBILE"
        assert query_daily.clicks == 150
        assert query_daily.impressions == 2000
        assert query_daily.ctr == 0.075
        assert query_daily.position == 5.2

    def test_query_daily_defaults(self, session, test_project):
        """Test GSC query daily default values."""
        query_daily = GSCQueryDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            query="test query"
        )
        session.add(query_daily)
        session.commit()
        session.refresh(query_daily)

        assert query_daily.clicks == 0
        assert query_daily.impressions == 0
        assert query_daily.ctr == 0.0
        assert query_daily.position == 0.0
        assert query_daily.page is None
        assert query_daily.country is None
        assert query_daily.device is None

    def test_query_daily_multiple_records(self, session, test_project):
        """Test creating multiple query daily records."""
        queries = [
            GSCQueryDaily(
                project_id=test_project.id,
                date=date(2024, 1, 15),
                query="query 1",
                clicks=100
            ),
            GSCQueryDaily(
                project_id=test_project.id,
                date=date(2024, 1, 16),
                query="query 2",
                clicks=200
            ),
        ]
        for q in queries:
            session.add(q)
        session.commit()

        # Query all records
        statement = select(GSCQueryDaily).where(GSCQueryDaily.project_id == test_project.id)
        results = session.exec(statement).all()

        assert len(results) == 2


class TestGSCPageDaily:
    """Test GSCPageDaily model."""

    def test_create_page_daily(self, session, test_project):
        """Test creating a GSC page daily record."""
        page_daily = GSCPageDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            page="https://example.com/page",
            country="USA",
            device="DESKTOP",
            clicks=50,
            impressions=1000,
            ctr=0.05,
            position=8.5
        )
        session.add(page_daily)
        session.commit()
        session.refresh(page_daily)

        assert page_daily.id is not None
        assert page_daily.project_id == test_project.id
        assert page_daily.date == date(2024, 1, 15)
        assert page_daily.page == "https://example.com/page"
        assert page_daily.country == "USA"
        assert page_daily.device == "DESKTOP"
        assert page_daily.clicks == 50
        assert page_daily.impressions == 1000
        assert page_daily.ctr == 0.05
        assert page_daily.position == 8.5

    def test_page_daily_defaults(self, session, test_project):
        """Test GSC page daily default values."""
        page_daily = GSCPageDaily(
            project_id=test_project.id,
            date=date(2024, 1, 15),
            page="https://example.com/page"
        )
        session.add(page_daily)
        session.commit()
        session.refresh(page_daily)

        assert page_daily.clicks == 0
        assert page_daily.impressions == 0
        assert page_daily.ctr == 0.0
        assert page_daily.position == 0.0
        assert page_daily.country is None
        assert page_daily.device is None


class TestKeywordCluster:
    """Test KeywordCluster model."""

    def test_create_keyword_cluster(self, session, test_project):
        """Test creating a keyword cluster."""
        cluster = KeywordCluster(
            project_id=test_project.id,
            label="Product Pages",
            algorithm="kmeans",
            total_clicks=500,
            total_impressions=10000,
            avg_position=7.5,
            query_count=25
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        assert cluster.id is not None
        assert cluster.project_id == test_project.id
        assert cluster.label == "Product Pages"
        assert cluster.algorithm == "kmeans"
        assert cluster.total_clicks == 500
        assert cluster.total_impressions == 10000
        assert cluster.avg_position == 7.5
        assert cluster.query_count == 25
        assert cluster.created_at is not None

    def test_keyword_cluster_defaults(self, session, test_project):
        """Test keyword cluster default values."""
        cluster = KeywordCluster(
            project_id=test_project.id,
            label="Test Cluster",
            algorithm="kmeans"
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        assert cluster.total_clicks == 0
        assert cluster.total_impressions == 0
        assert cluster.avg_position == 0.0
        assert cluster.query_count == 0


class TestKeywordClusterMember:
    """Test KeywordClusterMember model."""

    def test_create_cluster_member(self, session, test_project):
        """Test creating a keyword cluster member."""
        # Create cluster first
        cluster = KeywordCluster(
            project_id=test_project.id,
            label="Test Cluster",
            algorithm="kmeans"
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        # Create member
        member = KeywordClusterMember(
            cluster_id=cluster.id,
            query="test keyword",
            weight=0.85
        )
        session.add(member)
        session.commit()
        session.refresh(member)

        assert member.id is not None
        assert member.cluster_id == cluster.id
        assert member.query == "test keyword"
        assert member.weight == 0.85

    def test_cluster_member_defaults(self, session, test_project):
        """Test cluster member default values."""
        cluster = KeywordCluster(
            project_id=test_project.id,
            label="Test Cluster",
            algorithm="kmeans"
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        member = KeywordClusterMember(
            cluster_id=cluster.id,
            query="test keyword"
        )
        session.add(member)
        session.commit()
        session.refresh(member)

        assert member.weight == 0.0

    def test_cluster_member_relationship(self, session, test_project):
        """Test relationship between cluster and members."""
        cluster = KeywordCluster(
            project_id=test_project.id,
            label="Test Cluster",
            algorithm="kmeans"
        )
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        members = [
            KeywordClusterMember(cluster_id=cluster.id, query="query 1", weight=0.9),
            KeywordClusterMember(cluster_id=cluster.id, query="query 2", weight=0.8),
        ]
        for m in members:
            session.add(m)
        session.commit()

        # Test relationship
        assert cluster.members is not None
        assert len(cluster.members) == 2


class TestAPIResponseModels:
    """Test API response models."""

    def test_gsc_property_public(self):
        """Test GSCPropertyPublic model."""
        prop_public = GSCPropertyPublic(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            site_url="sc-domain:example.com",
            permission_level="siteOwner",
            verified=True,
            linked_at=datetime.now(timezone.utc),
            last_sync_at=None,
            sync_status="pending",
            sync_error=None,
            search_type="web"
        )
        assert prop_public.site_url == "sc-domain:example.com"

    def test_gsc_query_row(self):
        """Test GSCQueryRow model."""
        query_row = GSCQueryRow(
            query="test query",
            clicks=100,
            impressions=1000,
            ctr=0.1,
            position=5.5
        )
        assert query_row.query == "test query"
        assert query_row.clicks == 100

    def test_gsc_queries_response(self):
        """Test GSCQueriesResponse model."""
        rows = [
            GSCQueryRow(query="query 1", clicks=100, impressions=1000, ctr=0.1, position=5.0),
            GSCQueryRow(query="query 2", clicks=200, impressions=2000, ctr=0.1, position=6.0),
        ]
        response = GSCQueriesResponse(data=rows, count=2)
        assert response.count == 2
        assert len(response.data) == 2

    def test_opportunity_row(self):
        """Test OpportunityRow model."""
        opp = OpportunityRow(
            query="opportunity query",
            impressions=5000,
            clicks=50,
            ctr=0.01,
            position=15.5,
            opportunity_type="high_impressions_low_ctr",
            potential_clicks=200
        )
        assert opp.query == "opportunity query"
        assert opp.opportunity_type == "high_impressions_low_ctr"
        assert opp.potential_clicks == 200

    def test_cluster_public(self):
        """Test ClusterPublic model."""
        cluster = ClusterPublic(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            label="Test Cluster",
            algorithm="kmeans",
            created_at=datetime.now(timezone.utc),
            total_clicks=500,
            total_impressions=10000,
            avg_position=7.5,
            query_count=25
        )
        assert cluster.label == "Test Cluster"
        assert cluster.algorithm == "kmeans"
