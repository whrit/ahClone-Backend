"""
Test-Driven Development tests for SERP API Provider.
These tests verify the SerpAPIProvider implementation.
"""

import pytest
import respx
import httpx

from app.services.serp.providers.api_provider import SerpAPIProvider
from app.services.serp.providers.base import (
    ProviderStatus,
    ProviderResponse,
    SerpResult,
)
from app.core.config import settings


@pytest.fixture
def api_provider():
    """Create a SerpAPIProvider instance for testing."""
    return SerpAPIProvider()


@pytest.fixture
def mock_serp_api_success_response():
    """Mock successful SERP API response data."""
    return {
        "search_metadata": {
            "status": "Success",
            "total_results": 3,
        },
        "organic_results": [
            {
                "position": 1,
                "link": "https://www.example.com/page1",
                "title": "Example Page 1",
            },
            {
                "position": 2,
                "link": "https://test.org/page2",
                "title": "Test Page 2",
            },
            {
                "position": 3,
                "link": "https://www.demo.net/page3",
                "title": "Demo Page 3",
            },
        ],
    }


class TestSerpAPIProviderMetadata:
    """Test SerpAPIProvider class metadata."""

    def test_provider_key(self, api_provider):
        """Test provider_key is correctly set."""
        assert api_provider.provider_key == "serp_api"

    def test_display_name(self, api_provider):
        """Test display_name is correctly set."""
        assert api_provider.display_name == "SERP API (Licensed)"

    def test_is_compliant(self, api_provider):
        """Test is_compliant is True for licensed API."""
        assert api_provider.is_compliant is True


class TestSerpAPIProviderInitialization:
    """Test SerpAPIProvider initialization."""

    def test_initialization_loads_config(self, api_provider):
        """Test that initialization loads API key and URL from settings."""
        assert api_provider.api_key == settings.SERP_API_KEY
        assert api_provider.api_url == settings.SERP_API_URL

    def test_initialization_with_session(self):
        """Test initialization with database session."""
        mock_session = object()
        provider = SerpAPIProvider(session=mock_session)
        assert provider.session is mock_session


class TestSerpAPIProviderErrorHandling:
    """Test error handling in SerpAPIProvider."""

    @pytest.mark.asyncio
    async def test_returns_error_when_api_key_not_configured(self, monkeypatch):
        """Test that provider returns ERROR when API key is not configured."""
        # Temporarily set API key to empty
        monkeypatch.setattr(settings, "SERP_API_KEY", "")

        provider = SerpAPIProvider()
        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        assert response.status == ProviderStatus.ERROR
        assert "not configured" in response.error_message.lower()
        assert response.results == []
        assert response.total_results is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_handles_rate_limit_429_response(self, api_provider, monkeypatch):
        """Test that provider returns RATE_LIMITED on 429 response."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock 429 response
        respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(429, json={"error": "Rate limit exceeded"})
        )

        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        assert response.status == ProviderStatus.RATE_LIMITED
        assert "rate limit" in response.error_message.lower()
        assert response.results == []
        assert response.total_results is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_handles_http_error(self, api_provider, monkeypatch):
        """Test that provider returns ERROR on HTTP error."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock 500 error response
        respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(500, json={"error": "Internal server error"})
        )

        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        assert response.status == ProviderStatus.ERROR
        assert "http error" in response.error_message.lower()
        assert response.results == []
        assert response.total_results is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_handles_request_exception(self, api_provider, monkeypatch):
        """Test that provider returns ERROR on request exception."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock network error
        respx.get(settings.SERP_API_URL).mock(
            side_effect=httpx.RequestError("Network error")
        )

        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        assert response.status == ProviderStatus.ERROR
        assert "request error" in response.error_message.lower()
        assert response.results == []
        assert response.total_results is None


class TestSerpAPIProviderSuccessfulFetch:
    """Test successful SERP data fetching."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch_returns_results(
        self, api_provider, mock_serp_api_success_response, monkeypatch
    ):
        """Test successful fetch with mocked httpx response."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock successful response
        respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(200, json=mock_serp_api_success_response)
        )

        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
            depth=10,
        )

        assert response.status == ProviderStatus.SUCCESS
        assert response.error_message is None
        assert len(response.results) == 3
        assert response.total_results == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_parses_serp_results_correctly(
        self, api_provider, mock_serp_api_success_response, monkeypatch
    ):
        """Test that SERP results are parsed correctly."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock successful response
        respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(200, json=mock_serp_api_success_response)
        )

        response = await provider.fetch_serp(
            keyword="test keyword",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        # Check first result
        first_result = response.results[0]
        assert first_result.rank == 1
        assert first_result.url == "https://www.example.com/page1"
        assert first_result.domain == "example.com"
        assert first_result.title == "Example Page 1"
        assert first_result.snippet is None  # Not in mock data

        # Check second result
        second_result = response.results[1]
        assert second_result.rank == 2
        assert second_result.url == "https://test.org/page2"
        assert second_result.domain == "test.org"

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_correct_request_parameters(
        self, api_provider, mock_serp_api_success_response, monkeypatch
    ):
        """Test that correct request parameters are sent to API."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock successful response and capture request
        route = respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(200, json=mock_serp_api_success_response)
        )

        await provider.fetch_serp(
            keyword="test keyword",
            locale="en-GB",
            device="mobile",
            search_engine="google",
            depth=20,
        )

        # Verify request was made
        assert route.called

        # Get the request and check parameters
        request = route.calls.last.request
        params = dict(request.url.params)

        assert params["api_key"] == "test_api_key"
        assert params["q"] == "test keyword"
        assert params["engine"] == "google"
        assert params["gl"] == "GB"  # Country from locale
        assert params["hl"] == "en"  # Language from locale
        assert params["num"] == "20"
        assert params["device"] == "mobile"


class TestSerpAPIProviderHelperMethods:
    """Test helper methods in SerpAPIProvider."""

    def test_parse_locale_with_country(self, api_provider):
        """Test locale parsing with country code."""
        language, country = api_provider._parse_locale("en-US")
        assert language == "en"
        assert country == "US"

    def test_parse_locale_with_different_country(self, api_provider):
        """Test locale parsing with different country."""
        language, country = api_provider._parse_locale("fr-FR")
        assert language == "fr"
        assert country == "FR"

    def test_parse_locale_without_country(self, api_provider):
        """Test locale parsing without country (defaults to US)."""
        language, country = api_provider._parse_locale("en")
        assert language == "en"
        assert country == "US"

    def test_extract_domain_from_full_url(self, api_provider):
        """Test domain extraction from full URL."""
        domain = api_provider._extract_domain("https://www.example.com/path/to/page")
        assert domain == "example.com"

    def test_extract_domain_without_www(self, api_provider):
        """Test domain extraction from URL without www."""
        domain = api_provider._extract_domain("https://example.com/path")
        assert domain == "example.com"

    def test_extract_domain_from_http_url(self, api_provider):
        """Test domain extraction from HTTP URL."""
        domain = api_provider._extract_domain("http://test.org/page")
        assert domain == "test.org"

    def test_extract_domain_from_empty_url(self, api_provider):
        """Test domain extraction from empty URL."""
        domain = api_provider._extract_domain("")
        assert domain == ""


class TestSerpAPIProviderDeviceHandling:
    """Test device-specific parameter handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_desktop_device_no_parameter(
        self, api_provider, mock_serp_api_success_response, monkeypatch
    ):
        """Test that desktop device doesn't add device parameter."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock successful response
        route = respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(200, json=mock_serp_api_success_response)
        )

        await provider.fetch_serp(
            keyword="test",
            locale="en-US",
            device="desktop",
            search_engine="google",
        )

        # Check that device parameter is not in request for desktop
        request = route.calls.last.request
        params = dict(request.url.params)
        assert "device" not in params or params.get("device") == "desktop"

    @pytest.mark.asyncio
    @respx.mock
    async def test_tablet_device_parameter(
        self, api_provider, mock_serp_api_success_response, monkeypatch
    ):
        """Test that tablet device adds correct parameter."""
        # Set a test API key
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_api_key")
        provider = SerpAPIProvider()

        # Mock successful response
        route = respx.get(settings.SERP_API_URL).mock(
            return_value=httpx.Response(200, json=mock_serp_api_success_response)
        )

        await provider.fetch_serp(
            keyword="test",
            locale="en-US",
            device="tablet",
            search_engine="google",
        )

        # Check that device parameter is set for tablet
        request = route.calls.last.request
        params = dict(request.url.params)
        assert params["device"] == "tablet"
