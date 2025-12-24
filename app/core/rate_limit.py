"""Rate limiting configuration using slowapi"""
import os
import sys

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_identifier(request: Request) -> str:
    """
    Get rate limit identifier - prefer user ID if authenticated, else IP.

    This allows us to track rate limits per user when authenticated,
    and per IP address for unauthenticated requests.

    Args:
        request: The incoming request

    Returns:
        Identifier string for rate limiting (e.g., "user:123" or "ip:192.168.1.1")
    """
    # Try to get user from request state (set by auth middleware)
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"
    return get_remote_address(request)


# Check if we're running tests
# Use multiple detection methods for reliability:
# 1. pytest in sys.modules - set when pytest is imported (reliable during collection)
# 2. PYTEST_CURRENT_TEST - set during test execution
# 3. RATE_LIMIT_TESTING=1 - manual override to enable rate limiting in tests
_is_testing = (
    "pytest" in sys.modules
    or os.environ.get("PYTEST_CURRENT_TEST") is not None
)
# Allow manual override to enable rate limiting during specific tests
_enable_rate_limiting = os.environ.get("RATE_LIMIT_TESTING") == "1"

# Use very high limits during tests to avoid rate limiting issues
_default_limit = "10000/minute" if _is_testing else "100/minute"

limiter = Limiter(
    key_func=get_identifier,
    default_limits=[_default_limit],
    storage_uri="memory://",  # Use Redis in production: "redis://localhost:6379"
    headers_enabled=True,  # Enable rate limit headers in responses
    enabled=_enable_rate_limiting if _is_testing else True,  # Disable rate limiting during tests unless explicitly enabled
)


# Common rate limit decorators for reuse across routes
def standard_limit() -> str:
    """
    Standard API rate limit: 100 requests/minute.

    Use this for most API endpoints that are not resource-intensive.

    Returns:
        Rate limit string
    """
    return "100/minute"


def strict_limit() -> str:
    """
    Strict rate limit for expensive operations: 10 requests/minute.

    Use this for resource-intensive operations like:
    - Starting audits
    - Syncing data from external APIs
    - Backfilling historical data
    - Generating reports

    Returns:
        Rate limit string
    """
    return "10/minute"


def auth_limit() -> str:
    """
    Rate limit for authentication endpoints: 5 requests/minute.

    Use this for authentication-related endpoints to prevent:
    - Brute force attacks
    - Credential stuffing
    - Account enumeration

    Returns:
        Rate limit string
    """
    return "5/minute"
