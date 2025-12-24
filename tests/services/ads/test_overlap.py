"""Tests for SEO + PPC Overlap Analysis Service."""
# ruff: noqa: ARG001
import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session

from app import crud
from app.models import User
from app.models.ads import AdsKeywordDaily
from app.models.gsc import GSCQueryDaily
from app.models.project import Project
from app.services.ads.overlap import OverlapAnalyzer, OverlapResult


def create_paid_keyword(
    project_id: uuid.UUID,
    keyword_text: str,
    date_offset_days: int = 1,
    clicks: int = 100,
    impressions: int = 1000,
    cost_micros: int = 5_000_000,
    conversions: float = 10.0,
) -> AdsKeywordDaily:
    """Helper function to create paid keyword data."""
    return AdsKeywordDaily(
        project_id=project_id,
        date=date.today() - timedelta(days=date_offset_days),
        campaign_id="campaign1",
        ad_group_id="adgroup1",
        criterion_id="criterion1",
        keyword_text=keyword_text,
        match_type="EXACT",
        clicks=clicks,
        impressions=impressions,
        cost_micros=cost_micros,
        conversions=conversions,
        average_cpc_micros=cost_micros // clicks if clicks > 0 else 0,
    )


def create_organic_keyword(
    project_id: uuid.UUID,
    query: str,
    date_offset_days: int = 1,
    clicks: int = 50,
    impressions: int = 500,
    position: float = 3.5,
) -> GSCQueryDaily:
    """Helper function to create organic keyword data."""
    ctr = clicks / impressions if impressions > 0 else 0.0
    return GSCQueryDaily(
        project_id=project_id,
        date=date.today() - timedelta(days=date_offset_days),
        query=query,
        page="https://example.com/page1",
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
    )


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
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
    return user


@pytest.fixture
def test_project(db: Session, test_user: User) -> Project:
    """Create a test project for overlap analysis."""
    project = Project(
        name="Test Overlap Project",
        seed_url="https://example.com",
        created_by_id=test_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def overlap_analyzer(db: Session) -> OverlapAnalyzer:
    """Create an OverlapAnalyzer instance."""
    return OverlapAnalyzer(session=db)


@pytest.fixture(autouse=True)
def cleanup_test_data(db: Session, test_project: Project) -> None:
    """Clean up test data after each test."""
    yield
    # Clean up ads and gsc data
    from sqlmodel import delete
    db.exec(delete(AdsKeywordDaily).where(AdsKeywordDaily.project_id == test_project.id))
    db.exec(delete(GSCQueryDaily).where(GSCQueryDaily.project_id == test_project.id))
    db.commit()


class TestComputeOverlapBasic:
    """Test basic overlap computation functionality."""

    def test_overlap_with_both_paid_and_organic(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test overlap detection when keyword appears in both paid and organic."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "test keyword"))
        db.add(create_organic_keyword(project_id, "test keyword"))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        result = results[0]
        assert result.keyword == "test keyword"
        assert result.paid_clicks == 100
        assert result.paid_cost == 5.0
        assert result.paid_cpc == 0.05
        assert result.organic_clicks == 50
        assert result.organic_impressions == 500
        assert result.organic_position == 3.5
        assert result.overlap_type == "both"
        assert result.opportunity_score > 0

    def test_overlap_with_paid_only_keyword(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test detection of paid-only keywords (opportunity to build organic)."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "paid only keyword", clicks=200, cost_micros=10_000_000))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        result = results[0]
        assert result.keyword == "paid only keyword"
        assert result.paid_clicks == 200
        assert result.paid_cost == 10.0
        assert result.organic_clicks == 0
        assert result.organic_impressions == 0
        assert result.organic_position == 0.0
        assert result.overlap_type == "paid_only"
        assert result.opportunity_score > 0

    def test_overlap_with_organic_only_keyword(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test detection of organic-only keywords."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "organic only keyword", clicks=30, impressions=300, position=8.5))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        result = results[0]
        assert result.keyword == "organic only keyword"
        assert result.paid_clicks == 0
        assert result.paid_cost == 0.0
        assert result.organic_clicks == 30
        assert result.organic_impressions == 300
        assert result.organic_position == 8.5
        assert result.overlap_type == "organic_only"
        assert result.opportunity_score > 0


class TestOverlapTypeClassification:
    """Test overlap_type classification logic."""

    def test_both_classification_with_matching_keywords(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that matching keywords are classified as 'both'."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "shared keyword", clicks=50, cost_micros=2_500_000))
        db.add(create_organic_keyword(project_id, "shared keyword", clicks=25, impressions=250, position=4.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "shared keyword")
        assert result.overlap_type == "both"

    def test_paid_only_classification(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that keywords with only paid data are classified as 'paid_only'."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "paid exclusive"))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "paid exclusive")
        assert result.overlap_type == "paid_only"

    def test_organic_only_classification(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that keywords with only organic data are classified as 'organic_only'."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "organic exclusive", clicks=40, impressions=400, position=6.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "organic exclusive")
        assert result.overlap_type == "organic_only"


class TestOpportunityScoreCalculation:
    """Test opportunity_score calculation for each overlap type."""

    def test_both_high_score_for_good_organic_position(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that 'both' type with good organic position (<5) has high opportunity to reduce paid spend."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "high opportunity", cost_micros=10_000_000))
        db.add(create_organic_keyword(project_id, "high opportunity", position=2.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "high opportunity")
        assert result.overlap_type == "both"
        assert result.opportunity_score > 50

    def test_both_low_score_for_poor_organic_position(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that 'both' type with poor organic position (>=5) has lower opportunity."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "low opportunity", clicks=50, cost_micros=2_500_000))
        db.add(create_organic_keyword(project_id, "low opportunity", clicks=10, impressions=100, position=8.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "low opportunity")
        assert result.overlap_type == "both"
        assert result.opportunity_score < 50

    def test_paid_only_score_based_on_cost(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that 'paid_only' type opportunity score is based on paid cost."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "expensive paid", cost_micros=20_000_000))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "expensive paid")
        assert result.overlap_type == "paid_only"
        assert result.opportunity_score > 0

    def test_organic_only_high_score_for_poor_position(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that 'organic_only' type with position > 5 has high opportunity for paid coverage."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "poor position organic", clicks=20, impressions=500, position=12.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "poor position organic")
        assert result.overlap_type == "organic_only"
        assert result.opportunity_score > 30

    def test_organic_only_low_score_for_good_position(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that 'organic_only' type with position <= 5 has low opportunity for paid."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "good position organic", clicks=50, impressions=500, position=3.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        result = next(r for r in results if r.keyword == "good position organic")
        assert result.overlap_type == "organic_only"
        assert result.opportunity_score < 30


class TestEdgeCases:
    """Test edge cases and data handling."""

    def test_empty_paid_data_returns_organic_only(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test handling when there is no paid data."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "organic keyword", clicks=25, impressions=250, position=5.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        assert results[0].overlap_type == "organic_only"
        assert results[0].paid_clicks == 0
        assert results[0].paid_cost == 0.0

    def test_empty_organic_data_returns_paid_only(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test handling when there is no organic data."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "paid keyword", clicks=75, impressions=750, cost_micros=3_750_000))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        assert results[0].overlap_type == "paid_only"
        assert results[0].organic_clicks == 0
        assert results[0].organic_impressions == 0

    def test_empty_both_returns_empty_list(
        self,
        overlap_analyzer: OverlapAnalyzer,
        test_project: Project,
    ) -> None:
        """Test that empty data returns empty list."""
        # Arrange
        project_id = test_project.id

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 0


class TestDateRangeFiltering:
    """Test date range filtering."""

    def test_filters_by_period_days(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that only data within period_days is included."""
        # Arrange
        project_id = test_project.id

        # Recent data (within 28 days)
        db.add(create_paid_keyword(project_id, "recent keyword", date_offset_days=10))
        # Old data (outside 28 days)
        db.add(create_paid_keyword(project_id, "old keyword", date_offset_days=60))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        assert results[0].keyword == "recent keyword"

    def test_custom_period_days(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test custom period_days parameter."""
        # Arrange
        project_id = test_project.id

        db.add(create_organic_keyword(project_id, "5 day old", date_offset_days=5))
        db.add(create_organic_keyword(project_id, "10 day old", date_offset_days=10))
        db.commit()

        # Act - Use 7 day period
        results = overlap_analyzer.compute_overlap(project_id, period_days=7)

        # Assert - Only 5-day-old data should be included
        assert len(results) == 1
        assert results[0].keyword == "5 day old"


class TestKeywordNormalization:
    """Test keyword normalization (case-insensitive matching)."""

    def test_case_insensitive_matching(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that keywords are matched case-insensitively."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "Test Keyword", clicks=50, cost_micros=2_500_000))
        db.add(create_organic_keyword(project_id, "test keyword", clicks=25, impressions=250, position=4.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert - Should match as one keyword (case-insensitive)
        assert len(results) == 1
        assert results[0].keyword == "test keyword"
        assert results[0].overlap_type == "both"

    def test_mixed_case_keywords_combined(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that mixed case variations are combined."""
        # Arrange
        project_id = test_project.id

        db.add(create_paid_keyword(project_id, "UPPER CASE", date_offset_days=1, clicks=30, cost_micros=1_500_000))
        db.add(create_paid_keyword(project_id, "upper case", date_offset_days=2, clicks=20, cost_micros=1_000_000))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert - Should combine into one result
        assert len(results) == 1
        assert results[0].keyword == "upper case"
        assert results[0].paid_clicks == 50  # 30 + 20


class TestSortingByOpportunityScore:
    """Test results are sorted by opportunity_score descending."""

    def test_results_sorted_by_opportunity_score(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that results are sorted by opportunity_score in descending order."""
        # Arrange
        project_id = test_project.id

        # High opportunity - good organic position with high paid cost
        db.add(create_paid_keyword(project_id, "high opp", cost_micros=20_000_000))
        db.add(create_organic_keyword(project_id, "high opp", position=2.0))

        # Medium opportunity - paid only with moderate cost
        db.add(create_paid_keyword(project_id, "medium opp", clicks=50, cost_micros=5_000_000))

        # Low opportunity - organic only with good position
        db.add(create_organic_keyword(project_id, "low opp", clicks=20, impressions=200, position=3.0))

        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 3
        # Verify descending order
        assert results[0].opportunity_score >= results[1].opportunity_score
        assert results[1].opportunity_score >= results[2].opportunity_score
        # High opportunity should be first
        assert results[0].keyword == "high opp"


class TestAggregation:
    """Test keyword metric aggregation."""

    def test_aggregates_multiple_days(
        self,
        overlap_analyzer: OverlapAnalyzer,
        db: Session,
        test_project: Project,
    ) -> None:
        """Test that metrics are aggregated across multiple days."""
        # Arrange
        project_id = test_project.id

        # Same keyword over multiple days
        db.add(create_paid_keyword(project_id, "multi day", date_offset_days=1, clicks=30, cost_micros=1_500_000))
        db.add(create_paid_keyword(project_id, "multi day", date_offset_days=2, clicks=20, cost_micros=1_000_000))
        db.add(create_organic_keyword(project_id, "multi day", date_offset_days=1, clicks=15, impressions=150, position=4.0))
        db.add(create_organic_keyword(project_id, "multi day", date_offset_days=2, clicks=10, impressions=100, position=5.0))
        db.commit()

        # Act
        results = overlap_analyzer.compute_overlap(project_id, period_days=28)

        # Assert
        assert len(results) == 1
        result = results[0]
        assert result.keyword == "multi day"
        assert result.paid_clicks == 50  # 30 + 20
        assert result.paid_cost == 2.5  # 1.5 + 1.0
        assert result.organic_clicks == 25  # 15 + 10
        assert result.organic_impressions == 250  # 150 + 100
        # Position should be weighted average: (4.0 * 150 + 5.0 * 100) / 250 = 4.4
        assert abs(result.organic_position - 4.4) < 0.01
