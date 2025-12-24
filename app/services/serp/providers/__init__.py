"""SERP data providers."""
from app.services.serp.providers.base import (
    ProviderRegistry,
    ProviderResponse,
    ProviderStatus,
    SerpProvider,
    SerpResult,
)

# Create singleton provider registry instance
provider_registry = ProviderRegistry()

__all__ = [
    "SerpProvider",
    "SerpResult",
    "ProviderResponse",
    "ProviderStatus",
    "ProviderRegistry",
    "provider_registry",
]
