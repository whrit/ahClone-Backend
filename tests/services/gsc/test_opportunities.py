"""Tests for GSC Opportunity Finder Service (TDD)."""
# ruff: noqa: ARG001
from datetime import date, timedelta

import pytest
from sqlmodel import Session

from app import crud
from app.models import User
from app.models.gsc import GSCQueryDaily
from app.models.project import Project
from app.services.gsc.opportunities import (
    OpportunityFinder,
    OpportunityType,
)


@pytest.fixture
def test_project(db: Session) -> Project:
    """Create a test project for opportunity testing."""
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
        name="Test Opportunity Project",
        seed_url="https://example.com",
        created_by_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def opportunity_finder(db: Session) -> OpportunityFinder:
    """Create an OpportunityFinder instance."""
    return OpportunityFinder(db)


@pytest.fixture
def clean_gsc_data(db: Session):
    """Clean up GSC data before and after each test."""
    # Clean before
    from sqlmodel import delete
    statement = delete(GSCQueryDaily)
    db.execute(statement)
    db.commit()

    yield

    # Clean after
    statement = delete(GSCQueryDaily)
    db.execute(statement)
    db.commit()


class TestOpportunityFinder:
    """Test suite for OpportunityFinder service."""

    def test_find_opportunities_low_ctr(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test finding LOW_CTR opportunities (high impressions, low CTR)."""
        # Arrange: Create test data with high impressions but low CTR
        today = date.today()
        for day_offset in range(28):  # 28 days of data
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="best python tutorial",
                page="https://example.com/python",
                clicks=5,
                impressions=500,  # High impressions
                ctr=0.01,  # 1% CTR (below 2% threshold)
                position=5.0,
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should find LOW_CTR opportunity
        assert len(opportunities) > 0
        low_ctr_opps = [o for o in opportunities if o.opportunity_type == OpportunityType.LOW_CTR]
        assert len(low_ctr_opps) > 0

        opp = low_ctr_opps[0]
        assert opp.query == "best python tutorial"
        assert opp.impressions >= 100
        assert opp.ctr < 0.02
        assert opp.score > 0
        # Score formula: impressions * (0.02 - ctr)
        expected_score = opp.impressions * (0.02 - opp.ctr)
        assert abs(opp.score - expected_score) < 0.01

    def test_find_opportunities_position_8_20(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test finding POSITION_8_20 opportunities (quick wins)."""
        # Arrange: Create test data with position 8-20 and sufficient impressions
        today = date.today()
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="python frameworks",
                page="https://example.com/frameworks",
                clicks=20,
                impressions=300,  # Above threshold
                ctr=0.067,  # ~6.7% CTR
                position=12.0,  # Position 12 (quick win range)
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should find POSITION_8_20 opportunity
        assert len(opportunities) > 0
        position_opps = [o for o in opportunities if o.opportunity_type == OpportunityType.POSITION_8_20]
        assert len(position_opps) > 0

        opp = position_opps[0]
        assert opp.query == "python frameworks"
        assert 8 <= opp.position <= 20
        assert opp.impressions >= 100
        assert opp.score > 0
        # Score formula: impressions * (1 - ctr) * (1 / position)
        expected_score = opp.impressions * (1 - opp.ctr) * (1 / opp.position)
        assert abs(opp.score - expected_score) < 0.01

    def test_find_opportunities_rising(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test finding RISING opportunities (improving position)."""
        # Arrange: Create current period with position 8 and prior period with position 12
        today = date.today()

        # Current period (28 days): position 8
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="django tutorial",
                page="https://example.com/django",
                clicks=30,
                impressions=400,
                ctr=0.075,
                position=8.0,  # Improved position
            )
            db.add(query_data)

        # Prior period (28 days before): position 12
        for day_offset in range(28, 56):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="django tutorial",
                page="https://example.com/django",
                clicks=25,
                impressions=400,
                ctr=0.0625,
                position=12.0,  # Previous position (worse)
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should find RISING opportunity
        assert len(opportunities) > 0
        rising_opps = [o for o in opportunities if o.opportunity_type == OpportunityType.RISING]
        assert len(rising_opps) > 0

        opp = rising_opps[0]
        assert opp.query == "django tutorial"
        assert opp.change_pct < 0  # Position improved (lower is better)
        assert abs(opp.change_pct) >= 2  # At least 2 position improvement
        assert opp.score > 0
        # Score formula: position_change * impressions (change is positive value)
        expected_score = abs(opp.change_pct) * opp.impressions
        assert abs(opp.score - expected_score) < 0.01

    def test_find_opportunities_falling(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test finding FALLING opportunities (declining position)."""
        # Arrange: Create current period with position 15 and prior period with position 8
        today = date.today()

        # Current period (28 days): position 15
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="flask tutorial",
                page="https://example.com/flask",
                clicks=15,
                impressions=350,
                ctr=0.043,
                position=15.0,  # Declined position
            )
            db.add(query_data)

        # Prior period (28 days before): position 8
        for day_offset in range(28, 56):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="flask tutorial",
                page="https://example.com/flask",
                clicks=25,
                impressions=350,
                ctr=0.071,
                position=8.0,  # Previous better position
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should find FALLING opportunity
        assert len(opportunities) > 0
        falling_opps = [o for o in opportunities if o.opportunity_type == OpportunityType.FALLING]
        assert len(falling_opps) > 0

        opp = falling_opps[0]
        assert opp.query == "flask tutorial"
        assert opp.change_pct > 0  # Position got worse (higher is worse)
        assert abs(opp.change_pct) >= 2  # At least 2 position decline
        assert opp.score > 0
        # Score formula: abs(position_change) * impressions
        expected_score = abs(opp.change_pct) * opp.impressions
        assert abs(opp.score - expected_score) < 0.01

    def test_min_impressions_threshold(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test that queries below MIN_IMPRESSIONS threshold are excluded."""
        # Arrange: Create test data below impressions threshold
        today = date.today()
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="rare query",
                page="https://example.com/rare",
                clicks=1,
                impressions=3,  # Below 100 threshold
                ctr=0.01,  # Low CTR but shouldn't matter
                position=10.0,  # Quick win position but shouldn't matter
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should NOT find any opportunities for this query
        rare_query_opps = [o for o in opportunities if o.query == "rare query"]
        assert len(rare_query_opps) == 0

    def test_get_period_aggregates_structure(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test that _get_period_aggregates returns correct data structure."""
        # Arrange: Create test data
        today = date.today()
        for day_offset in range(7):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="test query",
                page="https://example.com/test",
                clicks=10,
                impressions=100,
                ctr=0.1,
                position=5.0,
            )
            db.add(query_data)
        db.commit()

        # Act: Get period aggregates
        start_date = today - timedelta(days=6)
        end_date = today
        aggregates = opportunity_finder._get_period_aggregates(
            project_id=test_project.id,
            start_date=start_date,
            end_date=end_date
        )

        # Assert: Should return dict with correct structure
        assert isinstance(aggregates, dict)
        assert "test query" in aggregates

        query_data = aggregates["test query"]
        assert "clicks" in query_data
        assert "impressions" in query_data
        assert "ctr" in query_data
        assert "position" in query_data

        # Check aggregated values
        assert query_data["clicks"] == 70  # 10 clicks * 7 days
        assert query_data["impressions"] == 700  # 100 impressions * 7 days
        assert abs(query_data["ctr"] - 0.1) < 0.01
        assert abs(query_data["position"] - 5.0) < 0.01

    def test_empty_data_returns_no_opportunities(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test that empty data returns no opportunities."""
        # Arrange: No data in database (clean_gsc_data fixture ensures this)

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should return empty list
        assert len(opportunities) == 0

    def test_multiple_opportunity_types_same_query(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test that a single query can have multiple opportunity types."""
        # Arrange: Create data that qualifies for both LOW_CTR and POSITION_8_20
        today = date.today()
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="multi opportunity",
                page="https://example.com/multi",
                clicks=5,
                impressions=500,  # High impressions
                ctr=0.01,  # Low CTR (< 2%)
                position=12.0,  # Quick win position (8-20)
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities
        opportunities = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,
            period_days=28,
            compare_days=28
        ))

        # Assert: Should find multiple opportunity types for same query
        multi_opps = [o for o in opportunities if o.query == "multi opportunity"]
        assert len(multi_opps) >= 2  # Should have at least LOW_CTR and POSITION_8_20

        opportunity_types = {o.opportunity_type for o in multi_opps}
        assert OpportunityType.LOW_CTR in opportunity_types
        assert OpportunityType.POSITION_8_20 in opportunity_types

    def test_uuid_project_id_support(
        self,
        db: Session,
        test_project: Project,
        opportunity_finder: OpportunityFinder,
        clean_gsc_data
    ):
        """Test that both string and UUID project IDs are supported."""
        # Arrange: Create test data
        today = date.today()
        for day_offset in range(28):
            query_data = GSCQueryDaily(
                project_id=test_project.id,
                date=today - timedelta(days=day_offset),
                query="uuid test",
                page="https://example.com/uuid",
                clicks=5,
                impressions=500,
                ctr=0.01,
                position=5.0,
            )
            db.add(query_data)
        db.commit()

        # Act: Find opportunities using UUID
        opportunities_uuid = list(opportunity_finder.find_opportunities(
            project_id=test_project.id,  # UUID type
            period_days=28,
            compare_days=28
        ))

        # Act: Find opportunities using string UUID
        opportunities_str = list(opportunity_finder.find_opportunities(
            project_id=str(test_project.id),  # String type
            period_days=28,
            compare_days=28
        ))

        # Assert: Both should return same results
        assert len(opportunities_uuid) == len(opportunities_str)
        assert len(opportunities_uuid) > 0
