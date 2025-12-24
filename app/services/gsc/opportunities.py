"""GSC Opportunity Finder Service - Identify SEO opportunities."""
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

from sqlmodel import Session, func, select

from app.models.gsc import GSCQueryDaily


class OpportunityType(str, Enum):
    """Types of SEO opportunities."""
    LOW_CTR = "low_ctr"           # High impressions, low CTR
    POSITION_8_20 = "position_8_20"  # Bottom of page 1 / top of page 2
    RISING = "rising"             # Improving position
    FALLING = "falling"           # Declining position


@dataclass
class Opportunity:
    """Represents a single SEO opportunity."""
    query: str
    page: str | None
    clicks: int
    impressions: int
    ctr: float
    position: float
    opportunity_type: OpportunityType
    score: float
    change_pct: float = 0.0


class OpportunityFinder:
    """Find keyword opportunities from GSC data."""

    # Thresholds
    LOW_CTR_THRESHOLD = 0.02  # 2% CTR
    MIN_IMPRESSIONS = 100
    POSITION_RANGE = (8, 20)  # Position 8-20 (quick wins)

    def __init__(self, session: Session):
        """
        Initialize the opportunity finder.

        Args:
            session: Database session
        """
        self.session = session

    def find_opportunities(
        self,
        project_id: str | uuid.UUID,
        period_days: int = 28,
        compare_days: int = 28,
    ) -> Iterator[Opportunity]:
        """
        Find all opportunity types.

        Steps:
        1. Calculate date ranges (current and prior period)
        2. Get aggregated metrics per query for both periods
        3. For each query, check opportunity rules:
           - LOW_CTR: impressions >= 100 AND ctr < 0.02
           - POSITION_8_20: position between 8-20 AND impressions >= 100
           - RISING: position improved by 2+ positions vs prior
           - FALLING: position declined by 2+ positions vs prior
        4. Calculate score based on opportunity type
        5. Yield Opportunity objects

        Args:
            project_id: Project UUID or string UUID
            period_days: Number of days in current period (default 28)
            compare_days: Number of days in comparison period (default 28)

        Yields:
            Opportunity objects for each detected opportunity
        """
        # Convert string to UUID if needed
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)

        # Calculate date ranges
        today = date.today()
        current_end = today
        current_start = today - timedelta(days=period_days - 1)
        prior_end = current_start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=compare_days - 1)

        # Get aggregated metrics for both periods
        current_aggregates = self._get_period_aggregates(
            project_id, current_start, current_end
        )
        prior_aggregates = self._get_period_aggregates(
            project_id, prior_start, prior_end
        )

        # Track which queries we've already yielded opportunities for
        # to avoid duplicates per (query, type) combination
        yielded: set[tuple[str, OpportunityType]] = set()

        # Check each query for opportunities
        for query, current_data in current_aggregates.items():
            impressions = current_data["impressions"]
            clicks = current_data["clicks"]
            ctr = current_data["ctr"]
            position = current_data["position"]
            page = current_data.get("page")

            # Skip queries below minimum impressions threshold
            if impressions < self.MIN_IMPRESSIONS:
                continue

            # Check LOW_CTR opportunity
            if ctr < self.LOW_CTR_THRESHOLD:
                score = impressions * (self.LOW_CTR_THRESHOLD - ctr)
                key = (query, OpportunityType.LOW_CTR)
                if key not in yielded:
                    yielded.add(key)
                    yield Opportunity(
                        query=query,
                        page=page,
                        clicks=clicks,
                        impressions=impressions,
                        ctr=ctr,
                        position=position,
                        opportunity_type=OpportunityType.LOW_CTR,
                        score=score,
                        change_pct=0.0,
                    )

            # Check POSITION_8_20 opportunity
            if self.POSITION_RANGE[0] <= position <= self.POSITION_RANGE[1]:
                score = impressions * (1 - ctr) * (1 / position)
                key = (query, OpportunityType.POSITION_8_20)
                if key not in yielded:
                    yielded.add(key)
                    yield Opportunity(
                        query=query,
                        page=page,
                        clicks=clicks,
                        impressions=impressions,
                        ctr=ctr,
                        position=position,
                        opportunity_type=OpportunityType.POSITION_8_20,
                        score=score,
                        change_pct=0.0,
                    )

            # Check RISING/FALLING opportunities (requires prior data)
            if query in prior_aggregates:
                prior_position = prior_aggregates[query]["position"]
                position_change = position - prior_position

                # RISING: position improved (lower is better in SEO)
                if position_change <= -2:  # Position improved by at least 2
                    score = abs(position_change) * impressions
                    key = (query, OpportunityType.RISING)
                    if key not in yielded:
                        yielded.add(key)
                        yield Opportunity(
                            query=query,
                            page=page,
                            clicks=clicks,
                            impressions=impressions,
                            ctr=ctr,
                            position=position,
                            opportunity_type=OpportunityType.RISING,
                            score=score,
                            change_pct=position_change,
                        )

                # FALLING: position declined (higher is worse in SEO)
                elif position_change >= 2:  # Position declined by at least 2
                    score = abs(position_change) * impressions
                    key = (query, OpportunityType.FALLING)
                    if key not in yielded:
                        yielded.add(key)
                        yield Opportunity(
                            query=query,
                            page=page,
                            clicks=clicks,
                            impressions=impressions,
                            ctr=ctr,
                            position=position,
                            opportunity_type=OpportunityType.FALLING,
                            score=score,
                            change_pct=position_change,
                        )

    def _get_period_aggregates(
        self, project_id: str | uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, dict[str, Any]]:
        """
        Get aggregated metrics per query for a date range.

        Returns dict[query] = {clicks, impressions, position, ctr, page}

        Uses SQLModel select with func.sum and func.avg to aggregate
        metrics across the date range.

        Args:
            project_id: Project UUID or string UUID
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            Dictionary mapping query strings to their aggregated metrics
        """
        # Convert string to UUID if needed
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)

        # Build query to aggregate metrics per query
        # Type ignore needed for SQLAlchemy select with mixed column types and labels
        statement = (
            select(  # type: ignore[call-overload]
                GSCQueryDaily.query,
                func.sum(GSCQueryDaily.clicks).label("total_clicks"),
                func.sum(GSCQueryDaily.impressions).label("total_impressions"),
                func.avg(GSCQueryDaily.position).label("avg_position"),
                func.avg(GSCQueryDaily.ctr).label("avg_ctr"),
                GSCQueryDaily.page,
            )
            .where(GSCQueryDaily.project_id == project_id)
            .where(GSCQueryDaily.date >= start_date)
            .where(GSCQueryDaily.date <= end_date)
            .group_by(GSCQueryDaily.query, GSCQueryDaily.page)
        )

        results = self.session.exec(statement).all()

        # Build aggregates dictionary
        aggregates: dict[str, dict[str, Any]] = {}
        for row in results:
            query = row.query
            # If query already exists, sum up metrics across different pages
            if query in aggregates:
                aggregates[query]["clicks"] += row.total_clicks
                aggregates[query]["impressions"] += row.total_impressions
                # Recalculate weighted averages for position and CTR
                total_impr = aggregates[query]["impressions"]
                aggregates[query]["position"] = (
                    aggregates[query]["position"] * (total_impr - row.total_impressions) +
                    row.avg_position * row.total_impressions
                ) / total_impr
                aggregates[query]["ctr"] = (
                    aggregates[query]["ctr"] * (total_impr - row.total_impressions) +
                    row.avg_ctr * row.total_impressions
                ) / total_impr
            else:
                aggregates[query] = {
                    "clicks": row.total_clicks,
                    "impressions": row.total_impressions,
                    "position": row.avg_position,
                    "ctr": row.avg_ctr,
                    "page": row.page,
                }

        return aggregates
