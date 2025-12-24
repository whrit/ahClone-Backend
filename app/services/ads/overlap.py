"""SEO + PPC Overlap Analysis Service."""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, func, select

from app.models.ads import AdsKeywordDaily
from app.models.gsc import GSCQueryDaily


@dataclass
class OverlapResult:
    """Represents keyword overlap between paid and organic search."""
    keyword: str
    paid_clicks: int
    paid_cost: float
    paid_cpc: float
    organic_clicks: int
    organic_impressions: int
    organic_position: float
    overlap_type: str  # "both", "paid_only", "organic_only"
    opportunity_score: float


class OverlapAnalyzer:
    """Analyze overlap between paid and organic keywords."""

    def __init__(self, session: Session):
        """
        Initialize the overlap analyzer.

        Args:
            session: Database session
        """
        self.session = session

    def compute_overlap(
        self, project_id: uuid.UUID, period_days: int = 28
    ) -> list[OverlapResult]:
        """
        Compute SEO + PPC keyword overlap.

        Steps:
        1. Query AdsKeywordDaily for paid keywords (aggregated)
        2. Query GSCQueryDaily for organic keywords (aggregated)
        3. Compute overlap between paid and organic keyword sets
        4. Calculate opportunity scores:
           - "both": If organic position < 5, opportunity to reduce paid spend
           - "paid_only": Opportunity to build organic presence
           - "organic_only": If position > 5, opportunity to add paid coverage
        5. Sort by opportunity_score descending

        Args:
            project_id: Project UUID
            period_days: Number of days to analyze (default 28)

        Returns:
            List of OverlapResult objects sorted by opportunity_score descending
        """
        # Calculate date range
        today = date.today()
        start_date = today - timedelta(days=period_days - 1)
        end_date = today

        # Get aggregated paid keyword data
        paid_data = self._get_paid_aggregates(project_id, start_date, end_date)

        # Get aggregated organic keyword data
        organic_data = self._get_organic_aggregates(project_id, start_date, end_date)

        # Combine all keywords (case-insensitive)
        all_keywords = set(paid_data.keys()) | set(organic_data.keys())

        # Build overlap results
        results: list[OverlapResult] = []
        for keyword in all_keywords:
            paid = paid_data.get(keyword, {})
            organic = organic_data.get(keyword, {})

            # Determine overlap type
            has_paid = keyword in paid_data
            has_organic = keyword in organic_data

            if has_paid and has_organic:
                overlap_type = "both"
            elif has_paid:
                overlap_type = "paid_only"
            else:
                overlap_type = "organic_only"

            # Extract metrics
            paid_clicks = paid.get("clicks", 0)
            paid_cost = paid.get("cost", 0.0)
            paid_cpc = paid.get("cpc", 0.0)
            organic_clicks = organic.get("clicks", 0)
            organic_impressions = organic.get("impressions", 0)
            organic_position = organic.get("position", 0.0)

            # Calculate opportunity score based on overlap type
            opportunity_score = self._calculate_opportunity_score(
                overlap_type=overlap_type,
                paid_cost=paid_cost,
                organic_position=organic_position,
                organic_impressions=organic_impressions,
            )

            results.append(
                OverlapResult(
                    keyword=keyword,
                    paid_clicks=paid_clicks,
                    paid_cost=paid_cost,
                    paid_cpc=paid_cpc,
                    organic_clicks=organic_clicks,
                    organic_impressions=organic_impressions,
                    organic_position=organic_position,
                    overlap_type=overlap_type,
                    opportunity_score=opportunity_score,
                )
            )

        # Sort by opportunity_score descending
        results.sort(key=lambda x: x.opportunity_score, reverse=True)

        return results

    def _get_paid_aggregates(
        self, project_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, dict[str, Any]]:
        """
        Get aggregated paid keyword metrics for a date range.

        Returns dict[keyword_lowercase] = {clicks, cost, cpc}

        Args:
            project_id: Project UUID
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            Dictionary mapping lowercase keyword strings to aggregated metrics
        """
        # Build query to aggregate paid metrics per keyword
        # Note: cost_micros needs to be divided by 1,000,000 for actual cost
        statement = (
            select(  # type: ignore[call-overload]
                AdsKeywordDaily.keyword_text,
                func.sum(AdsKeywordDaily.clicks).label("total_clicks"),
                func.sum(AdsKeywordDaily.cost_micros).label("total_cost_micros"),
                func.sum(AdsKeywordDaily.impressions).label("total_impressions"),
            )
            .where(AdsKeywordDaily.project_id == project_id)
            .where(AdsKeywordDaily.date >= start_date)
            .where(AdsKeywordDaily.date <= end_date)
            .group_by(AdsKeywordDaily.keyword_text)
        )

        results = self.session.exec(statement).all()

        # Build aggregates dictionary (normalized to lowercase)
        aggregates: dict[str, dict[str, Any]] = {}
        for row in results:
            keyword_lower = row.keyword_text.lower()

            # Convert cost from micros to dollars
            cost = row.total_cost_micros / 1_000_000.0
            clicks = row.total_clicks

            # Calculate CPC
            cpc = cost / clicks if clicks > 0 else 0.0

            # If keyword already exists (different case), combine metrics
            if keyword_lower in aggregates:
                aggregates[keyword_lower]["clicks"] += clicks
                aggregates[keyword_lower]["cost"] += cost
                # Recalculate CPC
                total_clicks = aggregates[keyword_lower]["clicks"]
                total_cost = aggregates[keyword_lower]["cost"]
                aggregates[keyword_lower]["cpc"] = (
                    total_cost / total_clicks if total_clicks > 0 else 0.0
                )
            else:
                aggregates[keyword_lower] = {
                    "clicks": clicks,
                    "cost": cost,
                    "cpc": cpc,
                }

        return aggregates

    def _get_organic_aggregates(
        self, project_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, dict[str, Any]]:
        """
        Get aggregated organic keyword metrics for a date range.

        Returns dict[query_lowercase] = {clicks, impressions, position}

        Args:
            project_id: Project UUID
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            Dictionary mapping lowercase query strings to aggregated metrics
        """
        # Build query to aggregate organic metrics per query
        # We need weighted average for position, so we calculate sum(position * impressions) / sum(impressions)
        statement = (
            select(  # type: ignore[call-overload]
                GSCQueryDaily.query,
                func.sum(GSCQueryDaily.clicks).label("total_clicks"),
                func.sum(GSCQueryDaily.impressions).label("total_impressions"),
                func.sum(GSCQueryDaily.position * GSCQueryDaily.impressions).label("weighted_position_sum"),
            )
            .where(GSCQueryDaily.project_id == project_id)
            .where(GSCQueryDaily.date >= start_date)
            .where(GSCQueryDaily.date <= end_date)
            .group_by(GSCQueryDaily.query)
        )

        results = self.session.exec(statement).all()

        # Build aggregates dictionary (normalized to lowercase)
        aggregates: dict[str, dict[str, Any]] = {}
        for row in results:
            query_lower = row.query.lower()

            # Calculate weighted average position
            weighted_avg_position = (
                row.weighted_position_sum / row.total_impressions
                if row.total_impressions > 0
                else 0.0
            )

            # If query already exists (different case), combine metrics
            if query_lower in aggregates:
                prev_clicks = aggregates[query_lower]["clicks"]
                prev_impressions = aggregates[query_lower]["impressions"]
                prev_weighted_sum = aggregates[query_lower]["weighted_sum"]

                new_clicks = prev_clicks + row.total_clicks
                new_impressions = prev_impressions + row.total_impressions
                new_weighted_sum = prev_weighted_sum + row.weighted_position_sum

                aggregates[query_lower]["clicks"] = new_clicks
                aggregates[query_lower]["impressions"] = new_impressions
                aggregates[query_lower]["weighted_sum"] = new_weighted_sum
                aggregates[query_lower]["position"] = (
                    new_weighted_sum / new_impressions if new_impressions > 0 else 0.0
                )
            else:
                aggregates[query_lower] = {
                    "clicks": row.total_clicks,
                    "impressions": row.total_impressions,
                    "weighted_sum": row.weighted_position_sum,
                    "position": weighted_avg_position,
                }

        return aggregates

    def _calculate_opportunity_score(
        self,
        overlap_type: str,
        paid_cost: float,
        organic_position: float,
        organic_impressions: int,
    ) -> float:
        """
        Calculate opportunity score based on overlap type and metrics.

        Scoring logic:
        - "both" with organic position < 5: High score (opportunity to reduce paid spend)
          Score = paid_cost * (5 - position) * 10
        - "both" with organic position >= 5: Lower score
          Score = paid_cost * 5
        - "paid_only": Score based on paid cost (opportunity to build organic)
          Score = paid_cost * 10
        - "organic_only" with position > 5: Score based on impressions (add paid coverage)
          Score = organic_impressions * (position - 5) / 10
        - "organic_only" with position <= 5: Low score (already ranking well)
          Score = organic_impressions / 100

        Args:
            overlap_type: "both", "paid_only", or "organic_only"
            paid_cost: Total paid cost in dollars
            organic_position: Average organic position
            organic_impressions: Total organic impressions

        Returns:
            Opportunity score (higher = greater opportunity)
        """
        if overlap_type == "both":
            # High opportunity if organic position is good (< 5) with paid spend
            if organic_position < 5:
                # Good position - opportunity to reduce paid spend
                return paid_cost * (5 - organic_position) * 10
            else:
                # Poor position - need both paid and organic improvement
                return paid_cost * 5

        elif overlap_type == "paid_only":
            # Opportunity to build organic presence for expensive paid keywords
            return paid_cost * 10

        else:  # organic_only
            # Opportunity to add paid coverage if position is poor
            if organic_position > 5:
                # Poor position with good impressions - add paid coverage
                return organic_impressions * (organic_position - 5) / 10
            else:
                # Good position - low opportunity for paid
                return organic_impressions / 100
