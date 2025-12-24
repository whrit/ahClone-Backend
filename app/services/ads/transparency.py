"""
Transparency Creative Service for fetching competitor ads.

This service integrates with transparency datasets like:
- Google Ads Transparency Center
- Meta Ad Library
- Other ad transparency sources

For MVP, this includes stub methods that can be extended with actual API integrations.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models.ads import TransparencyCreative


class TransparencyService:
    """
    Service for fetching and managing competitor ad creatives from transparency sources.

    This service provides methods to:
    1. Fetch competitor ads from transparency APIs (Google, Meta, etc.)
    2. Store creatives in the database
    3. Query and analyze competitor advertising strategies
    """

    def __init__(self, session: Session):
        """
        Initialize the TransparencyService.

        Args:
            session: SQLModel database session
        """
        self.session = session

    def fetch_competitor_ads(
        self,
        advertiser_name: str,
        source: str = "google_ads_transparency",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch competitor ads from transparency sources.

        This is currently a stub method that returns mock data.
        In production, this would integrate with:
        - Google Ads Transparency Center API
        - Meta Ad Library API
        - Other transparency data sources

        Args:
            advertiser_name: Name of the advertiser/competitor to search for
            source: Data source key (e.g., 'google_ads_transparency', 'meta')
            limit: Maximum number of ads to fetch

        Returns:
            List of ad creative dictionaries with structure:
            {
                'advertiser_id': str,
                'advertiser_name': str,
                'creative_id': str,
                'headline': str,
                'description': str,
                'image_url': str | None,
                'landing_url': str | None,
                'first_seen': date,
                'last_seen': date,
                'geo_targeting': list[str],
                'metadata': dict
            }
        """
        # TODO: Implement actual API integration
        # For now, return mock data for testing

        mock_ads = [
            {
                "advertiser_id": f"{advertiser_name.lower().replace(' ', '_')}_001",
                "advertiser_name": advertiser_name,
                "creative_id": f"creative_{i}",
                "headline": f"Sample Ad Headline {i}",
                "description": f"Sample ad description for {advertiser_name} - promoting their latest product or service.",
                "image_url": f"https://example.com/ads/image_{i}.jpg",
                "landing_url": f"https://example.com/landing/{i}",
                "first_seen": date.today() - timedelta(days=30),
                "last_seen": date.today(),
                "geo_targeting": ["US", "CA", "UK"],
                "metadata": {
                    "ad_format": "display",
                    "platforms": ["search", "display"],
                    "estimated_budget": "medium",
                },
            }
            for i in range(min(limit, 5))  # Return up to 5 mock ads
        ]

        return mock_ads

    def store_creatives(
        self, creatives: list[dict[str, Any]], source_key: str
    ) -> int:
        """
        Store fetched ad creatives in the database.

        Args:
            creatives: List of creative dictionaries from fetch_competitor_ads()
            source_key: Source identifier (e.g., 'google_ads_transparency', 'meta')

        Returns:
            Number of creatives successfully stored
        """
        stored_count = 0

        for creative_data in creatives:
            try:
                # Check if creative already exists
                existing_creative = self.session.exec(
                    select(TransparencyCreative).where(
                        TransparencyCreative.source_key == source_key,
                        TransparencyCreative.creative_id == creative_data["creative_id"],
                    )
                ).first()

                if existing_creative:
                    # Update existing creative with latest data
                    existing_creative.last_seen = creative_data["last_seen"]
                    existing_creative.headline = creative_data["headline"]
                    existing_creative.description = creative_data["description"]
                    existing_creative.image_url = creative_data.get("image_url")
                    existing_creative.landing_url = creative_data.get("landing_url")
                    existing_creative.geo_targeting = creative_data.get("geo_targeting", [])
                    existing_creative.metadata_json = creative_data.get("metadata", {})
                else:
                    # Create new creative record
                    new_creative = TransparencyCreative(
                        source_key=source_key,
                        advertiser_id=creative_data["advertiser_id"],
                        advertiser_name=creative_data["advertiser_name"],
                        creative_id=creative_data["creative_id"],
                        headline=creative_data["headline"],
                        description=creative_data["description"],
                        image_url=creative_data.get("image_url"),
                        landing_url=creative_data.get("landing_url"),
                        first_seen=creative_data["first_seen"],
                        last_seen=creative_data["last_seen"],
                        geo_targeting=creative_data.get("geo_targeting", []),
                        metadata_json=creative_data.get("metadata", {}),
                    )
                    self.session.add(new_creative)

                stored_count += 1

            except Exception as e:
                # Log error but continue processing other creatives
                print(f"Error storing creative {creative_data.get('creative_id')}: {e}")
                continue

        # Commit all changes
        self.session.commit()

        return stored_count

    def get_creatives_by_advertiser(
        self,
        advertiser_name: str,
        source_key: str | None = None,
        limit: int = 100,
    ) -> list[TransparencyCreative]:
        """
        Retrieve stored competitor ads for a specific advertiser.

        Args:
            advertiser_name: Name of the advertiser to search for
            source_key: Optional filter by source (e.g., 'google_ads_transparency')
            limit: Maximum number of creatives to return

        Returns:
            List of TransparencyCreative model instances
        """
        query = select(TransparencyCreative).where(
            TransparencyCreative.advertiser_name.ilike(f"%{advertiser_name}%")
        )

        if source_key:
            query = query.where(TransparencyCreative.source_key == source_key)

        query = query.order_by(TransparencyCreative.last_seen.desc()).limit(limit)

        return list(self.session.exec(query).all())

    def get_recent_creatives(
        self,
        days: int = 30,
        source_key: str | None = None,
        limit: int = 100,
    ) -> list[TransparencyCreative]:
        """
        Retrieve recently seen competitor ads.

        Args:
            days: Number of days to look back (default 30)
            source_key: Optional filter by source
            limit: Maximum number of creatives to return

        Returns:
            List of TransparencyCreative model instances
        """
        cutoff_date = date.today() - timedelta(days=days)

        query = select(TransparencyCreative).where(
            TransparencyCreative.last_seen >= cutoff_date
        )

        if source_key:
            query = query.where(TransparencyCreative.source_key == source_key)

        query = query.order_by(TransparencyCreative.last_seen.desc()).limit(limit)

        return list(self.session.exec(query).all())

    def sync_competitor_ads(
        self,
        advertiser_name: str,
        source_key: str = "google_ads_transparency",
    ) -> dict[str, Any]:
        """
        Fetch and store competitor ads in one operation.

        This is a convenience method that combines fetching and storing.

        Args:
            advertiser_name: Name of the competitor to sync
            source_key: Data source to use

        Returns:
            Dictionary with sync results:
            {
                'fetched': int,
                'stored': int,
                'advertiser': str,
                'source': str
            }
        """
        # Fetch ads from transparency source
        creatives = self.fetch_competitor_ads(
            advertiser_name=advertiser_name,
            source=source_key,
        )

        # Store in database
        stored_count = self.store_creatives(
            creatives=creatives,
            source_key=source_key,
        )

        return {
            "fetched": len(creatives),
            "stored": stored_count,
            "advertiser": advertiser_name,
            "source": source_key,
        }
