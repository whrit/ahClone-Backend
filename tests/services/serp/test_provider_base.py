"""
Test-Driven Development tests for SERP Provider Base Classes.
These tests are written FIRST to define the expected behavior.
"""
from abc import ABC
from collections.abc import Generator
from datetime import datetime, timezone

import pytest

from app.services.serp.providers.base import (
    ProviderRegistry,
    ProviderResponse,
    ProviderStatus,
    SerpProvider,
    SerpResult,
)

# ============================================================================
# ProviderStatus Enum Tests
# ============================================================================


class TestProviderStatus:
    """Test ProviderStatus enum values"""

    def test_status_enum_values(self) -> None:
        """Test that all required status values exist"""
        assert ProviderStatus.SUCCESS
        assert ProviderStatus.NOT_FOUND
        assert ProviderStatus.RATE_LIMITED
        assert ProviderStatus.ERROR
        assert ProviderStatus.BLOCKED

    def test_status_enum_members(self) -> None:
        """Test enum member count and names"""
        members = list(ProviderStatus)
        assert len(members) == 5
        assert ProviderStatus.SUCCESS in members
        assert ProviderStatus.NOT_FOUND in members
        assert ProviderStatus.RATE_LIMITED in members
        assert ProviderStatus.ERROR in members
        assert ProviderStatus.BLOCKED in members


# ============================================================================
# SerpResult Dataclass Tests
# ============================================================================


class TestSerpResult:
    """Test SerpResult dataclass"""

    def test_serp_result_creation(self) -> None:
        """Test creating a SerpResult with all fields"""
        result = SerpResult(
            rank=1,
            url="https://example.com",
            domain="example.com",
            title="Example Title",
            snippet="Example snippet text",
        )
        assert result.rank == 1
        assert result.url == "https://example.com"
        assert result.domain == "example.com"
        assert result.title == "Example Title"
        assert result.snippet == "Example snippet text"

    def test_serp_result_optional_fields(self) -> None:
        """Test creating a SerpResult with optional fields as None"""
        result = SerpResult(
            rank=1,
            url="https://example.com",
            domain="example.com",
            title=None,
            snippet=None,
        )
        assert result.rank == 1
        assert result.url == "https://example.com"
        assert result.domain == "example.com"
        assert result.title is None
        assert result.snippet is None

    def test_serp_result_is_dataclass(self) -> None:
        """Test that SerpResult is a dataclass"""
        from dataclasses import is_dataclass
        assert is_dataclass(SerpResult)


# ============================================================================
# ProviderResponse Dataclass Tests
# ============================================================================


class TestProviderResponse:
    """Test ProviderResponse dataclass"""

    def test_provider_response_creation_success(self) -> None:
        """Test creating a successful ProviderResponse"""
        now = datetime.now(timezone.utc)
        results = [
            SerpResult(
                rank=1,
                url="https://example.com",
                domain="example.com",
                title="Example",
                snippet="Text",
            )
        ]

        response = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            results=results,
            fetched_at=now,
            total_results=100,
            error_message=None,
            raw_response={"api_response": "data"},
            provider_metadata={"provider": "test"},
        )

        assert response.status == ProviderStatus.SUCCESS
        assert response.results == results
        assert response.fetched_at == now
        assert response.total_results == 100
        assert response.error_message is None
        assert response.raw_response == {"api_response": "data"}
        assert response.provider_metadata == {"provider": "test"}

    def test_provider_response_creation_error(self) -> None:
        """Test creating an error ProviderResponse"""
        now = datetime.now(timezone.utc)

        response = ProviderResponse(
            status=ProviderStatus.ERROR,
            results=[],
            fetched_at=now,
            total_results=None,
            error_message="API rate limit exceeded",
            raw_response=None,
            provider_metadata=None,
        )

        assert response.status == ProviderStatus.ERROR
        assert response.results == []
        assert response.error_message == "API rate limit exceeded"
        assert response.total_results is None
        assert response.raw_response is None
        assert response.provider_metadata is None

    def test_provider_response_is_dataclass(self) -> None:
        """Test that ProviderResponse is a dataclass"""
        from dataclasses import is_dataclass
        assert is_dataclass(ProviderResponse)


# ============================================================================
# SerpProvider Abstract Base Class Tests
# ============================================================================


class TestSerpProvider:
    """Test SerpProvider abstract base class"""

    def test_serp_provider_is_abstract(self) -> None:
        """Test that SerpProvider is an ABC"""
        assert issubclass(SerpProvider, ABC)

    def test_cannot_instantiate_serp_provider_directly(self) -> None:
        """Test that SerpProvider cannot be instantiated directly"""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            SerpProvider()  # type: ignore[abstract]

    def test_serp_provider_has_class_attributes(self) -> None:
        """Test that SerpProvider has required class attributes"""
        # Create a concrete implementation for testing
        class TestProvider(SerpProvider):
            provider_key = "test"
            display_name = "Test Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        provider = TestProvider()
        assert provider.provider_key == "test"
        assert provider.display_name == "Test Provider"
        assert provider.is_compliant is True

    def test_must_implement_fetch_serp(self) -> None:
        """Test that subclasses must implement fetch_serp"""
        class IncompleteProvider(SerpProvider):
            provider_key = "incomplete"
            display_name = "Incomplete Provider"
            is_compliant = True

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()  # type: ignore[abstract]


# ============================================================================
# SerpProvider Helper Methods Tests
# ============================================================================


class TestSerpProviderHelperMethods:
    """Test SerpProvider helper methods"""

    @pytest.fixture
    def concrete_provider(self) -> SerpProvider:
        """Create a concrete provider for testing"""
        class TestProvider(SerpProvider):
            provider_key = "test"
            display_name = "Test Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        return TestProvider()

    def test_find_domain_rank_found_exact_match(self, concrete_provider: SerpProvider) -> None:
        """Test finding domain rank with exact match"""
        results = [
            SerpResult(1, "https://other.com", "other.com", "Other", "Text"),
            SerpResult(2, "https://example.com/page", "example.com", "Example", "Text"),
            SerpResult(3, "https://another.com", "another.com", "Another", "Text"),
        ]

        rank, url = concrete_provider.find_domain_rank(results, "example.com")
        assert rank == 2
        assert url == "https://example.com/page"

    def test_find_domain_rank_found_subdomain(self, concrete_provider: SerpProvider) -> None:
        """Test finding domain rank with subdomain"""
        results = [
            SerpResult(1, "https://www.example.com/page", "www.example.com", "WWW", "Text"),
            SerpResult(2, "https://other.com", "other.com", "Other", "Text"),
        ]

        rank, url = concrete_provider.find_domain_rank(results, "example.com")
        assert rank == 1
        assert url == "https://www.example.com/page"

    def test_find_domain_rank_not_found(self, concrete_provider: SerpProvider) -> None:
        """Test finding domain rank when not found"""
        results = [
            SerpResult(1, "https://other.com", "other.com", "Other", "Text"),
            SerpResult(2, "https://another.com", "another.com", "Another", "Text"),
        ]

        rank, url = concrete_provider.find_domain_rank(results, "example.com")
        assert rank is None
        assert url is None

    def test_find_domain_rank_empty_results(self, concrete_provider: SerpProvider) -> None:
        """Test finding domain rank with empty results"""
        rank, url = concrete_provider.find_domain_rank([], "example.com")
        assert rank is None
        assert url is None

    def test_find_domain_rank_case_insensitive(self, concrete_provider: SerpProvider) -> None:
        """Test that domain matching is case-insensitive"""
        results = [
            SerpResult(1, "https://Example.COM/page", "Example.COM", "Example", "Text"),
        ]

        rank, url = concrete_provider.find_domain_rank(results, "example.com")
        assert rank == 1
        assert url == "https://Example.COM/page"


# ============================================================================
# ProviderRegistry Tests
# ============================================================================


class TestProviderRegistry:
    """Test ProviderRegistry class"""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> Generator[None, None, None]:
        """Clear the provider registry before each test"""
        ProviderRegistry._providers = {}
        yield
        ProviderRegistry._providers = {}

    def test_registry_register_decorator(self) -> None:
        """Test registering a provider using the decorator"""
        @ProviderRegistry.register
        class TestProvider(SerpProvider):
            provider_key = "test"
            display_name = "Test Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        # Check that provider is registered
        provider_class = ProviderRegistry.get("test")
        assert provider_class is TestProvider

    def test_registry_get_returns_none_for_unknown(self) -> None:
        """Test that get returns None for unknown provider"""
        provider_class = ProviderRegistry.get("unknown")
        assert provider_class is None

    def test_registry_multiple_providers(self) -> None:
        """Test registering multiple providers"""
        @ProviderRegistry.register
        class Provider1(SerpProvider):
            provider_key = "provider1"
            display_name = "Provider 1"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        @ProviderRegistry.register
        class Provider2(SerpProvider):
            provider_key = "provider2"
            display_name = "Provider 2"
            is_compliant = False

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        assert ProviderRegistry.get("provider1") is Provider1
        assert ProviderRegistry.get("provider2") is Provider2

    def test_registry_list_available_all(self, clear_registry: Generator[None, None, None]) -> None:
        """Test listing all available providers"""
        @ProviderRegistry.register
        class Provider1(SerpProvider):
            provider_key = "provider1"
            display_name = "Provider 1"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        @ProviderRegistry.register
        class Provider2(SerpProvider):
            provider_key = "provider2"
            display_name = "Provider 2"
            is_compliant = False

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        available = ProviderRegistry.list_available(compliant_only=False)
        assert len(available) == 2

        # Check that both providers are in the list
        keys = [p["key"] for p in available]
        assert "provider1" in keys
        assert "provider2" in keys

    def test_registry_list_available_compliant_only(self, clear_registry: Generator[None, None, None]) -> None:
        """Test listing only compliant providers"""
        @ProviderRegistry.register
        class CompliantProvider(SerpProvider):
            provider_key = "compliant"
            display_name = "Compliant Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        @ProviderRegistry.register
        class NonCompliantProvider(SerpProvider):
            provider_key = "non_compliant"
            display_name = "Non-Compliant Provider"
            is_compliant = False

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        available = ProviderRegistry.list_available(compliant_only=True)
        assert len(available) == 1
        assert available[0]["key"] == "compliant"
        assert available[0]["name"] == "Compliant Provider"
        assert available[0]["is_compliant"] is True

    def test_registry_list_available_structure(self, clear_registry: Generator[None, None, None]) -> None:
        """Test that list_available returns correct structure"""
        @ProviderRegistry.register
        class TestProvider(SerpProvider):
            provider_key = "test"
            display_name = "Test Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        available = ProviderRegistry.list_available()
        assert len(available) == 1

        provider_info = available[0]
        assert "key" in provider_info
        assert "name" in provider_info
        assert "is_compliant" in provider_info
        assert provider_info["key"] == "test"
        assert provider_info["name"] == "Test Provider"
        assert provider_info["is_compliant"] is True

    def test_registry_decorator_returns_class(self) -> None:
        """Test that the register decorator returns the class"""
        @ProviderRegistry.register
        class TestProvider(SerpProvider):
            provider_key = "test"
            display_name = "Test Provider"
            is_compliant = True

            async def fetch_serp(
                self, keyword: str, locale: str, device: str, search_engine: str, depth: int = 10
            ) -> ProviderResponse:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    results=[],
                    fetched_at=datetime.now(timezone.utc),
                    total_results=0,
                    error_message=None,
                    raw_response=None,
                    provider_metadata=None,
                )

        # The decorator should return the class unchanged
        assert TestProvider.provider_key == "test"
        assert TestProvider.display_name == "Test Provider"

        # Can still instantiate it
        instance = TestProvider()
        assert instance.provider_key == "test"
