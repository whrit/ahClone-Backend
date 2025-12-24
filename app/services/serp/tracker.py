"""
RankTracker service for orchestrating keyword ranking refresh.

This service coordinates SERP data fetching, rank position tracking,
and observation history management for keyword targets.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models import (
    KeywordTarget,
    Project,
    RankObservation,
    RefreshStatus,
    SerpSnapshot,
)
from app.services.serp.providers import provider_registry


class RankTracker:
    """
    Service for tracking keyword rankings across search engines.

    Orchestrates the complete rank tracking workflow:
    1. Fetch SERP data from provider
    2. Find domain rank in results
    3. Calculate position changes
    4. Create observations and snapshots
    5. Update keyword target cache
    """

    def __init__(self, session: Session):
        """
        Initialize the RankTracker.

        Args:
            session: Database session for persistence
        """
        self.session = session

    async def refresh_keyword(
        self,
        keyword_target: KeywordTarget,
        project: Project
    ) -> RankObservation:
        """
        Refresh ranking data for a keyword target.

        This method orchestrates the complete refresh workflow:
        1. Get provider from registry
        2. Fetch SERP data
        3. Find domain rank
        4. Calculate position change
        5. Create observation and snapshot
        6. Update keyword target cache

        Args:
            keyword_target: The keyword target to refresh
            project: The project this keyword belongs to

        Returns:
            RankObservation with the latest rank data
        """
        # Get provider from registry
        provider = provider_registry.create_instance(
            keyword_target.provider_key,
            session=self.session
        )

        if not provider:
            error_msg = f"Provider '{keyword_target.provider_key}' not found in registry"
            return self._create_error_observation(keyword_target, error_msg)

        try:
            # For GSC-based providers, ensure session is set
            if keyword_target.provider_key.lower() in ['gsc', 'google_search_console']:
                provider.session = self.session

            # Fetch SERP data
            serp_data = await provider.fetch_serp(
                keyword=keyword_target.keyword,
                country=keyword_target.locale.split('-')[1] if '-' in keyword_target.locale else None,
                language=keyword_target.locale.split('-')[0] if '-' in keyword_target.locale else None,
                location=None,
                device=keyword_target.device.value if keyword_target.device else None
            )

            # Create SERP snapshot
            snapshot = SerpSnapshot(
                keyword_target_id=keyword_target.id,
                results_json=serp_data,
                total_results=serp_data.get("total_results"),
                captured_at=datetime.now(timezone.utc)
            )
            self.session.add(snapshot)
            self.session.commit()
            self.session.refresh(snapshot)

            # Extract seed domain from project.seed_url
            parsed_url = urlparse(project.seed_url)
            seed_domain = parsed_url.netloc

            # Find domain rank in SERP results
            position, url = provider.find_domain_rank(serp_data, seed_domain)

            # Get previous observation for position change calculation
            previous_obs = self._get_previous_observation(keyword_target.id)

            # Calculate position change (positive = improvement)
            position_change = None
            if position is not None and previous_obs and previous_obs.rank is not None:
                # Improvement means rank number decreased (e.g., 5 -> 1 = +4)
                position_change = previous_obs.rank - position

            # Extract domain from URL if we have one
            domain = None
            if url:
                domain = urlparse(url).netloc

            # Create rank observation
            observation = RankObservation(
                keyword_target_id=keyword_target.id,
                rank=position if position is not None else 101,  # Use 101 if not found (beyond top 100)
                url=url,
                domain=domain,
                status=RefreshStatus.SUCCESS,
                observed_at=datetime.now(timezone.utc)
            )
            self.session.add(observation)

            # Update keyword_target cache
            keyword_target.latest_position = position
            keyword_target.position_change = position_change
            keyword_target.last_refresh_at = datetime.now(timezone.utc)
            keyword_target.last_refresh_status = RefreshStatus.SUCCESS
            keyword_target.updated_at = datetime.now(timezone.utc)

            self.session.add(keyword_target)
            self.session.commit()
            self.session.refresh(observation)

            return observation

        except Exception as e:
            # Handle any errors during refresh
            error_msg = f"Error refreshing keyword: {str(e)}"
            return self._create_error_observation(keyword_target, error_msg)

    def _get_previous_observation(self, keyword_target_id: uuid.UUID) -> RankObservation | None:
        """
        Get the most recent successful observation for a keyword target.

        Args:
            keyword_target_id: ID of the keyword target

        Returns:
            Most recent successful RankObservation or None if no observations exist
        """
        statement = (
            select(RankObservation)
            .where(RankObservation.keyword_target_id == keyword_target_id)
            .where(RankObservation.status == RefreshStatus.SUCCESS)
            .order_by(RankObservation.observed_at.desc())
        )
        result = self.session.exec(statement).first()
        return result

    def _create_error_observation(
        self,
        keyword_target: KeywordTarget,
        error_message: str
    ) -> RankObservation:
        """
        Create a failed observation when an error occurs.

        Args:
            keyword_target: The keyword target that failed
            error_message: Description of the error

        Returns:
            RankObservation with FAILED status
        """
        observation = RankObservation(
            keyword_target_id=keyword_target.id,
            rank=0,  # Use 0 to indicate error/not found
            url=None,
            domain=None,
            status=RefreshStatus.FAILED,
            observed_at=datetime.now(timezone.utc)
        )
        self.session.add(observation)

        # Update keyword_target status
        keyword_target.last_refresh_at = datetime.now(timezone.utc)
        keyword_target.last_refresh_status = RefreshStatus.FAILED
        keyword_target.updated_at = datetime.now(timezone.utc)

        self.session.add(keyword_target)
        self.session.commit()
        self.session.refresh(observation)

        return observation

    def get_rank_history(
        self,
        keyword_target_id: uuid.UUID,
        days: int = 30
    ) -> list[RankObservation]:
        """
        Get rank observation history for a keyword target.

        Args:
            keyword_target_id: ID of the keyword target
            days: Number of days of history to retrieve (default: 30)

        Returns:
            List of RankObservations ordered by observed_at descending (most recent first)
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        statement = (
            select(RankObservation)
            .where(RankObservation.keyword_target_id == keyword_target_id)
            .where(RankObservation.observed_at >= cutoff_date)
            .order_by(RankObservation.observed_at.desc())
        )

        results = self.session.exec(statement).all()
        return list(results)
