"""Google Search Console API client."""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx


class GSCClient:
    """Google Search Console API client."""

    BASE_URL = "https://searchconsole.googleapis.com/webmasters/v3"

    def __init__(self, access_token: str, refresh_token: str) -> None:
        """Initialize GSC client with OAuth tokens.

        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
        """
        self.access_token = access_token
        self.refresh_token = refresh_token

    async def _get_headers(self) -> dict[str, str]:
        """Get authorization headers.

        Returns:
            Dictionary with authorization header
        """
        return {"Authorization": f"Bearer {self.access_token}"}

    async def list_sites(self) -> list[dict[str, Any]]:
        """List all sites the user has access to in GSC.

        Returns:
            List of site dictionaries with siteUrl and permissionLevel

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        async with httpx.AsyncClient() as client:
            headers = await self._get_headers()
            response = await client.get(f"{self.BASE_URL}/sites", headers=headers)
            response.raise_for_status()
            result: list[dict[str, Any]] = response.json().get("siteEntry", [])
            return result

    async def get_site(self, site_url: str) -> dict[str, Any]:
        """Get site info by URL.

        Args:
            site_url: The URL of the site to retrieve

        Returns:
            Dictionary with site information

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        encoded_url = quote(site_url, safe="")
        async with httpx.AsyncClient() as client:
            headers = await self._get_headers()
            response = await client.get(
                f"{self.BASE_URL}/sites/{encoded_url}", headers=headers
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def query_search_analytics(
        self,
        site_url: str,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        search_type: str = "web",
        row_limit: int = 25000,
        start_row: int = 0,
    ) -> dict[str, Any]:
        """Query search analytics data.

        Args:
            site_url: The URL of the site to query
            start_date: Start date for the query
            end_date: End date for the query
            dimensions: List of dimensions to group by (e.g., ['query', 'page'])
            search_type: Type of search (web, image, video, news, discover, googleNews)
            row_limit: Maximum number of rows to return (max 25000)
            start_row: Zero-based index of the first row to return

        Returns:
            Dictionary with search analytics data including rows

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        encoded_url = quote(site_url, safe="")
        payload = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "searchType": search_type,
            "rowLimit": row_limit,
            "startRow": start_row,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = await self._get_headers()
            response = await client.post(
                f"{self.BASE_URL}/sites/{encoded_url}/searchAnalytics/query",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def query_all_rows(
        self,
        site_url: str,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        search_type: str = "web",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Iterate through all rows with pagination.

        Args:
            site_url: The URL of the site to query
            start_date: Start date for the query
            end_date: End date for the query
            dimensions: List of dimensions to group by (e.g., ['query', 'page'])
            search_type: Type of search (web, image, video, news, discover, googleNews)

        Yields:
            Individual row dictionaries from the API response

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        start_row = 0
        row_limit = 25000

        while True:
            result = await self.query_search_analytics(
                site_url=site_url,
                start_date=start_date,
                end_date=end_date,
                dimensions=dimensions,
                search_type=search_type,
                row_limit=row_limit,
                start_row=start_row,
            )

            rows = result.get("rows", [])
            if not rows:
                break

            for row in rows:
                yield row

            # If we got fewer rows than the limit, we've reached the end
            if len(rows) < row_limit:
                break

            start_row += row_limit
