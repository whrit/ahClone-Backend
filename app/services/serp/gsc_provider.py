"""
GSC-based SERP provider.

Uses Google Search Console data to provide first-party SERP position data.
This provider only shows data for the user's own domain (first-party data).
"""

import uuid
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.gsc import GSCQueryDaily
from app.services.serp.providers import SerpProvider, provider_registry


class GSCBasedProvider(SerpProvider):
    """
    GSC-based SERP provider.

    Fetches SERP data from the GSCQueryDaily table using historical data
    from the last 7 days (days 3-10 ago to avoid incomplete recent data).
    """

    def __init__(self, session: Session | None = None):
        """
        Initialize GSC provider.

        Args:
            session: SQLModel database session (required for this provider)
        """
        super().__init__(session)

    async def fetch_serp(
        self,
        keyword: str,
        country: str | None = None,
        language: str | None = None,
        location: str | None = None,
        device: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch SERP data from GSC historical data.

        Queries GSCQueryDaily for the keyword across the last 7 days (days 3-10),
        groups by page, calculates average position and sums clicks/impressions,
        and returns the top results ordered by average position.

        Args:
            keyword: Search keyword to fetch results for
            country: Country code (not used in GSC data)
            language: Language code (not used in GSC data)
            location: Geographic location (not used in GSC data)
            device: Device type (not used in GSC data)
            project_id: Project ID to filter data (required)

        Returns:
            Dictionary with SERP data structure
        """
        # Validate required parameters
        if self.session is None:
            return {
                "error": "Database session is required for GSC provider",
                "organic": [],
                "total_results": 0,
            }

        if project_id is None:
            return {
                "error": "project_id is required for GSC provider",
                "organic": [],
                "total_results": 0,
            }

        try:
            # Convert project_id to UUID
            project_uuid = uuid.UUID(project_id)
        except (ValueError, TypeError):
            return {
                "error": f"Invalid project_id format: {project_id}",
                "organic": [],
                "total_results": 0,
            }

        # Define date range: today - 3 days to today - 10 days
        today = date.today()
        end_date = today - timedelta(days=3)
        start_date = today - timedelta(days=10)

        try:
            # Query GSCQueryDaily for the keyword
            # Group by page, calculate avg position and sum clicks/impressions
            page_col = GSCQueryDaily.page
            if page_col is None:
                return {
                    "error": "Database schema error: page column not found",
                    "organic": [],
                    "total_results": 0,
                }

            statement = (
                select(
                    page_col,
                    func.avg(GSCQueryDaily.position).label("avg_position"),
                    func.sum(GSCQueryDaily.clicks).label("total_clicks"),
                    func.sum(GSCQueryDaily.impressions).label("total_impressions"),
                )
                .where(GSCQueryDaily.project_id == project_uuid)
                .where(GSCQueryDaily.query == keyword)
                .where(GSCQueryDaily.date >= start_date)
                .where(GSCQueryDaily.date <= end_date)
                .where(page_col.is_not(None))  # type: ignore[union-attr]
                .group_by(page_col)
                .order_by(func.avg(GSCQueryDaily.position))
                .limit(100)  # Reasonable limit
            )

            results = self.session.exec(statement).all()  # type: ignore[arg-type]

            # If no results found
            if not results:
                return {
                    "organic": [],
                    "total_results": 0,
                }

            # Convert to organic results format
            organic_results = []
            for idx, row in enumerate(results, start=1):
                # Row is a tuple of (page, avg_position, total_clicks, total_impressions)
                page_url = str(row[0])
                avg_position = float(row[1]) if row[1] is not None else 0.0
                total_clicks = int(row[2]) if row[2] is not None else 0
                total_impressions = int(row[3]) if row[3] is not None else 0

                # Extract domain from URL
                try:
                    parsed = urlparse(page_url)
                    domain = parsed.netloc or parsed.path.split('/')[0]
                except Exception:
                    domain = page_url

                organic_results.append({
                    "position": idx,
                    "url": page_url,
                    "domain": domain,
                    "title": None,  # GSC doesn't provide title
                    "description": None,  # GSC doesn't provide description
                    "avg_position": avg_position,  # GSC-specific: historical avg position
                    "clicks": total_clicks,  # GSC-specific: total clicks
                    "impressions": total_impressions,  # GSC-specific: total impressions
                })

            return {
                "organic": organic_results,
                "total_results": len(organic_results),
                "metadata": {
                    "source": "gsc",
                    "date_range_start": start_date.isoformat(),
                    "date_range_end": end_date.isoformat(),
                },
            }

        except Exception as e:
            return {
                "error": f"Database query failed: {str(e)}",
                "organic": [],
                "total_results": 0,
            }

    def find_domain_rank(self, serp_data: dict[str, Any], domain: str) -> tuple[int | None, str | None]:
        """
        Find the rank position of a domain in SERP results.

        Args:
            serp_data: SERP data from fetch_serp()
            domain: Domain to search for (e.g., "example.com")

        Returns:
            Tuple of (position, url) where position is 1-indexed, or (None, None) if not found
        """
        organic_results = serp_data.get("organic", [])
        domain_lower = domain.lower()

        for result in organic_results:
            result_domain = result.get("domain", "")
            if not result_domain:
                # Try to extract from URL
                url = result.get("url", "")
                try:
                    parsed = urlparse(url)
                    result_domain = parsed.netloc
                except Exception:
                    continue

            result_domain_lower = result_domain.lower()

            # Check for exact match or subdomain match
            if result_domain_lower == domain_lower or result_domain_lower.endswith(f".{domain_lower}"):
                return result.get("position"), result.get("url")

        return None, None


# Register the GSC provider
provider_registry.register("gsc_based", GSCBasedProvider)
