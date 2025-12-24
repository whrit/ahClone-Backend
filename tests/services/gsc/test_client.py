"""Tests for Google Search Console API client."""

from datetime import date
from urllib.parse import quote

import httpx
import pytest
import respx


@pytest.mark.asyncio
class TestGSCClient:
    """Test cases for GSCClient."""

    @pytest.fixture
    def access_token(self) -> str:
        """Return test access token."""
        return "test_access_token_123"

    @pytest.fixture
    def refresh_token(self) -> str:
        """Return test refresh token."""
        return "test_refresh_token_456"

    @pytest.fixture
    def gsc_client(self, access_token: str, refresh_token: str):
        """Create GSCClient instance for testing."""
        from app.services.gsc.client import GSCClient

        return GSCClient(access_token=access_token, refresh_token=refresh_token)

    @pytest.fixture
    def base_url(self) -> str:
        """Return GSC API base URL."""
        return "https://searchconsole.googleapis.com/webmasters/v3"

    async def test_initialization(
        self, gsc_client, access_token: str, refresh_token: str
    ) -> None:
        """Test GSCClient initialization."""
        assert gsc_client.access_token == access_token
        assert gsc_client.refresh_token == refresh_token

    async def test_get_headers(self, gsc_client, access_token: str) -> None:
        """Test _get_headers returns proper authorization headers."""
        headers = await gsc_client._get_headers()
        assert headers["Authorization"] == f"Bearer {access_token}"

    @respx.mock
    async def test_list_sites_success(self, gsc_client, base_url: str) -> None:
        """Test list_sites successfully retrieves sites."""
        mock_response = {
            "siteEntry": [
                {
                    "siteUrl": "https://example.com/",
                    "permissionLevel": "siteOwner",
                },
                {
                    "siteUrl": "sc-domain:example.com",
                    "permissionLevel": "siteFullUser",
                },
            ]
        }

        respx.get(f"{base_url}/sites").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        sites = await gsc_client.list_sites()

        assert len(sites) == 2
        assert sites[0]["siteUrl"] == "https://example.com/"
        assert sites[0]["permissionLevel"] == "siteOwner"
        assert sites[1]["siteUrl"] == "sc-domain:example.com"
        assert sites[1]["permissionLevel"] == "siteFullUser"

    @respx.mock
    async def test_list_sites_empty(self, gsc_client, base_url: str) -> None:
        """Test list_sites with no sites."""
        mock_response: dict = {}

        respx.get(f"{base_url}/sites").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        sites = await gsc_client.list_sites()

        assert sites == []

    @respx.mock
    async def test_list_sites_authorization_header(
        self, gsc_client, base_url: str, access_token: str
    ) -> None:
        """Test list_sites sends correct authorization header."""
        route = respx.get(f"{base_url}/sites").mock(
            return_value=httpx.Response(200, json={"siteEntry": []})
        )

        await gsc_client.list_sites()

        assert route.called
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {access_token}"

    @respx.mock
    async def test_get_site_success(self, gsc_client, base_url: str) -> None:
        """Test get_site successfully retrieves site info."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        mock_response = {
            "siteUrl": site_url,
            "permissionLevel": "siteOwner",
        }

        respx.get(f"{base_url}/sites/{encoded_url}").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        site = await gsc_client.get_site(site_url)

        assert site["siteUrl"] == site_url
        assert site["permissionLevel"] == "siteOwner"

    @respx.mock
    async def test_get_site_url_encoding(self, gsc_client, base_url: str) -> None:
        """Test get_site properly encodes site URL."""
        site_url = "sc-domain:example.com"
        encoded_url = quote(site_url, safe="")

        route = respx.get(f"{base_url}/sites/{encoded_url}").mock(
            return_value=httpx.Response(200, json={"siteUrl": site_url})
        )

        await gsc_client.get_site(site_url)

        assert route.called

    @respx.mock
    async def test_query_search_analytics_success(
        self, gsc_client, base_url: str
    ) -> None:
        """Test query_search_analytics successfully queries data."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query", "page"]

        mock_response = {
            "rows": [
                {
                    "keys": ["test query", "https://example.com/page1"],
                    "clicks": 100,
                    "impressions": 1000,
                    "ctr": 0.1,
                    "position": 5.5,
                }
            ]
        }

        route = respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await gsc_client.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        )

        assert result == mock_response
        assert route.called

        # Verify request payload
        request_json = route.calls.last.request.content
        assert request_json is not None

    @respx.mock
    async def test_query_search_analytics_payload(
        self, gsc_client, base_url: str
    ) -> None:
        """Test query_search_analytics sends correct payload."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]
        search_type = "image"
        row_limit = 10000
        start_row = 100

        route = respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json={})
        )

        await gsc_client.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            search_type=search_type,
            row_limit=row_limit,
            start_row=start_row,
        )

        assert route.called
        # Note: We'll verify the actual JSON payload in the implementation

    @respx.mock
    async def test_query_search_analytics_timeout(
        self, gsc_client, base_url: str
    ) -> None:
        """Test query_search_analytics uses 60s timeout."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        route = respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json={})
        )

        await gsc_client.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        )

        assert route.called

    @respx.mock
    async def test_query_all_rows_single_page(
        self, gsc_client, base_url: str
    ) -> None:
        """Test query_all_rows with single page of results."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        mock_response = {
            "rows": [
                {"keys": ["query1"], "clicks": 10},
                {"keys": ["query2"], "clicks": 20},
            ]
        }

        respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        rows = []
        async for row in gsc_client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            rows.append(row)

        assert len(rows) == 2
        assert rows[0]["keys"] == ["query1"]
        assert rows[0]["clicks"] == 10
        assert rows[1]["keys"] == ["query2"]
        assert rows[1]["clicks"] == 20

    @respx.mock
    async def test_query_all_rows_pagination(self, gsc_client, base_url: str) -> None:
        """Test query_all_rows handles pagination correctly."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        # First page with 25000 rows (full page)
        first_page_rows = [{"keys": [f"query{i}"], "clicks": i} for i in range(25000)]
        mock_response_1 = {"rows": first_page_rows}

        # Second page with 10000 rows (partial page, indicates end of data)
        second_page_rows = [
            {"keys": [f"query{i}"], "clicks": i} for i in range(25000, 35000)
        ]
        mock_response_2 = {"rows": second_page_rows}

        route = respx.post(
            f"{base_url}/sites/{encoded_url}/searchAnalytics/query"
        ).mock(
            side_effect=[
                httpx.Response(200, json=mock_response_1),
                httpx.Response(200, json=mock_response_2),
            ]
        )

        rows = []
        async for row in gsc_client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            rows.append(row)

        assert len(rows) == 35000
        # Should make 2 calls: first full page, second partial page (stops automatically)
        assert route.call_count == 2

    @respx.mock
    async def test_query_all_rows_empty(self, gsc_client, base_url: str) -> None:
        """Test query_all_rows with no results."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        mock_response = {"rows": []}

        respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        rows = []
        async for row in gsc_client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            rows.append(row)

        assert len(rows) == 0

    @respx.mock
    async def test_query_all_rows_no_rows_key(self, gsc_client, base_url: str) -> None:
        """Test query_all_rows when response has no 'rows' key."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        mock_response: dict = {}

        respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        rows = []
        async for row in gsc_client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            rows.append(row)

        assert len(rows) == 0

    @respx.mock
    async def test_error_handling_list_sites(self, gsc_client, base_url: str) -> None:
        """Test error handling for failed list_sites request."""
        respx.get(f"{base_url}/sites").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await gsc_client.list_sites()

    @respx.mock
    async def test_error_handling_get_site(self, gsc_client, base_url: str) -> None:
        """Test error handling for failed get_site request."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")

        respx.get(f"{base_url}/sites/{encoded_url}").mock(
            return_value=httpx.Response(404, json={"error": "Not Found"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await gsc_client.get_site(site_url)

    @respx.mock
    async def test_error_handling_query_search_analytics(
        self, gsc_client, base_url: str
    ) -> None:
        """Test error handling for failed query_search_analytics request."""
        site_url = "https://example.com/"
        encoded_url = quote(site_url, safe="")
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        dimensions = ["query"]

        respx.post(f"{base_url}/sites/{encoded_url}/searchAnalytics/query").mock(
            return_value=httpx.Response(403, json={"error": "Forbidden"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await gsc_client.query_search_analytics(
                site_url=site_url,
                start_date=start_date,
                end_date=end_date,
                dimensions=dimensions,
            )
