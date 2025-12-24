"""
Base classes and interfaces for SERP data providers.

This module defines the core abstractions for fetching and processing
search engine results page (SERP) data from various providers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ProviderStatus(Enum):
    """Status of a SERP provider response."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass
class SerpResult:
    """
    A single search result from a SERP.

    Attributes:
        rank: Position in search results (1-indexed)
        url: Full URL of the result
        domain: Domain name extracted from the URL
        title: Page title from search results (optional)
        snippet: Text snippet/description from search results (optional)
    """

    rank: int
    url: str
    domain: str
    title: str | None
    snippet: str | None


@dataclass
class ProviderResponse:
    """
    Response from a SERP provider.

    Attributes:
        status: Status of the provider response
        results: List of search results
        fetched_at: Timestamp when data was fetched
        total_results: Total number of results available (optional)
        error_message: Error message if status is ERROR or RATE_LIMITED (optional)
        raw_response: Raw API response data for debugging (optional)
        provider_metadata: Provider-specific metadata (optional)
    """

    status: ProviderStatus
    results: list[SerpResult]
    fetched_at: datetime
    total_results: int | None
    error_message: str | None
    raw_response: dict[str, Any] | None
    provider_metadata: dict[str, Any] | None


class SerpProvider(ABC):
    """
    Abstract base class for SERP data providers.

    All SERP providers must inherit from this class and implement
    the required abstract methods.

    Class Attributes:
        provider_key: Unique identifier for the provider
        display_name: Human-readable name for the provider
        is_compliant: Whether the provider complies with search engine ToS
    """

    provider_key: str
    display_name: str
    is_compliant: bool

    @abstractmethod
    async def fetch_serp(
        self,
        keyword: str,
        locale: str,
        device: str,
        search_engine: str,
        depth: int = 10,
    ) -> ProviderResponse:
        """
        Fetch SERP data for a keyword.

        Args:
            keyword: Search keyword to fetch results for
            locale: Locale/location for search (e.g., "en-US", "de-DE")
            device: Device type ("desktop" or "mobile")
            search_engine: Search engine to query (e.g., "google", "bing")
            depth: Number of results to fetch (default: 10)

        Returns:
            ProviderResponse containing results and metadata

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("Subclasses must implement fetch_serp")

    def find_domain_rank(
        self, results: list[SerpResult], target_domain: str
    ) -> tuple[int | None, str | None]:
        """
        Find the rank and URL of a target domain in search results.

        This helper method searches through results to find the first occurrence
        of a domain matching the target domain (case-insensitive). It matches
        both exact domains and subdomains (e.g., "example.com" matches
        "www.example.com", "blog.example.com", etc.).

        Args:
            results: List of search results to search through
            target_domain: Domain to search for (e.g., "example.com")

        Returns:
            Tuple of (rank, url) if found, or (None, None) if not found
        """
        target_domain_lower = target_domain.lower()

        for result in results:
            result_domain_lower = result.domain.lower()

            # Check for exact match or subdomain match
            if result_domain_lower == target_domain_lower or result_domain_lower.endswith(
                f".{target_domain_lower}"
            ):
                return result.rank, result.url

        return None, None


class ProviderRegistry:
    """
    Registry for managing SERP provider classes.

    This class provides a centralized way to register and retrieve
    SERP provider implementations.
    """

    _providers: dict[str, type[SerpProvider]] = {}

    @classmethod
    def register(cls, provider_class: type[SerpProvider]) -> type[SerpProvider]:
        """
        Register a SERP provider class.

        This is typically used as a decorator:

        @ProviderRegistry.register
        class MyProvider(SerpProvider):
            ...

        Args:
            provider_class: The provider class to register

        Returns:
            The provider class (unchanged, for use as decorator)
        """
        cls._providers[provider_class.provider_key] = provider_class
        return provider_class

    @classmethod
    def get(cls, provider_key: str) -> type[SerpProvider] | None:
        """
        Get a provider class by its key.

        Args:
            provider_key: The unique key of the provider

        Returns:
            The provider class, or None if not found
        """
        return cls._providers.get(provider_key)

    @classmethod
    def list_available(cls, compliant_only: bool = True) -> list[dict[str, Any]]:
        """
        List all available providers.

        Args:
            compliant_only: If True, only return compliant providers

        Returns:
            List of provider information dictionaries with keys:
            - key: Provider key
            - name: Display name
            - is_compliant: Compliance status
        """
        providers = []

        for provider_class in cls._providers.values():
            if compliant_only and not provider_class.is_compliant:
                continue

            providers.append(
                {
                    "key": provider_class.provider_key,
                    "name": provider_class.display_name,
                    "is_compliant": provider_class.is_compliant,
                }
            )

        return providers
