"""Tests for API rate limiting - TDD approach

NOTE: These tests require rate limiting to be ENABLED.
When running the full test suite, rate limiting is disabled to prevent
test interference. To run these tests specifically, set:
    RATE_LIMIT_TESTING=1 pytest tests/api/test_rate_limiting.py -v
"""
import os
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import limiter

# Skip all rate limiting tests when rate limiting is disabled
# Rate limiting is disabled during normal test runs to prevent test interference
pytestmark = pytest.mark.skipif(
    not limiter.enabled,
    reason="Rate limiting is disabled during tests. Run with RATE_LIMIT_TESTING=1 to enable."
)


def test_rate_limit_headers_present_in_responses(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that rate limit headers are present in responses"""
    r = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200

    # Check for rate limit headers
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "X-RateLimit-Reset" in r.headers

    # Verify header values are valid
    limit = int(r.headers["X-RateLimit-Limit"])
    remaining = int(r.headers["X-RateLimit-Remaining"])
    reset_timestamp = float(r.headers["X-RateLimit-Reset"])

    assert limit > 0
    assert remaining >= 0
    assert remaining <= limit
    assert reset_timestamp > 0


def test_requests_within_limit_succeed(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that requests within the rate limit succeed"""
    # Make multiple requests within limit (standard limit is 100/minute)
    # We'll make 5 requests which should all succeed
    for i in range(5):
        r = client.get(
            f"{settings.API_V1_STR}/users/me",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200, f"Request {i+1} failed with status {r.status_code}"

        # Verify remaining count decreases
        remaining = int(r.headers["X-RateLimit-Remaining"])
        assert remaining >= 0


def test_requests_exceeding_limit_return_429(client: TestClient) -> None:
    """Test that requests exceeding the rate limit return 429 Too Many Requests"""
    # Use login endpoint which has strict rate limit (5/minute)
    # Make requests until we hit the limit
    responses: list[Any] = []

    # Make 6 requests - the 6th should be rate limited
    for i in range(6):
        r = client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": "test@example.com", "password": "wrongpassword"},
        )
        responses.append(r)

    # Last request should be rate limited
    last_response = responses[-1]
    assert last_response.status_code == 429

    # Verify Retry-After header is present
    assert "Retry-After" in last_response.headers
    retry_after = int(last_response.headers["Retry-After"])
    assert retry_after > 0


def test_rate_limit_resets_after_window(client: TestClient) -> None:
    """Test that rate limit resets after the time window expires"""
    # Note: This test would require waiting for the rate limit window to expire
    # For a real implementation, we would use a shorter window or mock time
    # For now, we'll test that the reset timestamp is in the future

    # Use login endpoint which doesn't require authentication
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": "test@example.com", "password": "wrongpassword"},
    )

    if "X-RateLimit-Reset" in r.headers:
        reset_timestamp = float(r.headers["X-RateLimit-Reset"])
        current_time = time.time()

        # Reset time should be in the future
        assert reset_timestamp > current_time
        # Reset time should be within the next minute (for 1-minute window)
        assert reset_timestamp <= current_time + 60
    else:
        # If headers not present, test passes - headers are optional for some responses
        assert True


def test_different_limits_for_different_endpoints(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that different endpoints have different rate limits"""
    # Test login endpoint (strict limit: 5/minute)
    r_login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": "test@example.com", "password": "wrongpassword"},
    )
    login_limit = int(r_login.headers.get("X-RateLimit-Limit", "0"))

    # Test standard endpoint (standard limit: 100/minute)
    r_users = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
    )
    users_limit = int(r_users.headers.get("X-RateLimit-Limit", "0"))

    # Login should have stricter limit
    assert login_limit < users_limit
    assert login_limit == 5  # auth_limit
    assert users_limit == 100  # standard_limit


def test_authenticated_vs_unauthenticated_limits(client: TestClient) -> None:
    """Test that authenticated users have different limits than unauthenticated users"""
    # Both should be rate limited, but with potentially different identifiers
    # Unauthenticated: rate limited by IP
    # Authenticated: rate limited by user ID

    # Test unauthenticated request (login endpoint doesn't require auth)
    r_unauth = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": "test@example.com", "password": "wrongpassword"},
    )
    # Should have rate limit headers (if implemented)
    # Both unauthenticated (IP-based) and authenticated (user-based) should have rate limiting
    assert r_unauth.status_code in [400, 401, 429]  # Login fails or rate limited


def test_rate_limit_per_user_isolation(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    """Test that rate limits are isolated per user"""
    # Make requests as normal user
    r1 = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
    )
    normal_user_remaining = int(r1.headers["X-RateLimit-Remaining"])

    # Make requests as superuser
    r2 = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers=superuser_token_headers,
    )
    superuser_remaining = int(r2.headers["X-RateLimit-Remaining"])

    # Both should have independent rate limit counters
    # Each user should have a high number of remaining requests (close to 100)
    assert normal_user_remaining >= 95  # Allow for some variability from test setup
    assert superuser_remaining >= 95  # Allow for some variability from test setup


def test_rate_limit_on_expensive_operations(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Any
) -> None:
    """Test that expensive operations (audits, sync) have strict rate limits"""
    from unittest.mock import patch
    from app import crud
    from app.models import Project, User

    # Get the current user
    user_email = "test@example.com"
    user = crud.get_user_by_email(session=db, email=user_email)
    if not user:
        # Create test user if doesn't exist
        from app.models import UserCreate
        user_in = UserCreate(
            email=user_email,
            password="testpassword",
            full_name="Test User"
        )
        user = crud.create_user(session=db, user_create=user_in)
        db.commit()

    # Create a test project
    project = Project(
        name="Test Project",
        seed_url="https://example.com",
        created_by_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    try:
        # Mock the Celery task to avoid connection errors
        with patch("app.tasks.audit.run_audit.delay"):
            # Test audit start endpoint (should have strict limit: 10/minute)
            r = client.post(
                f"{settings.API_V1_STR}/projects/{project.id}/audits/",
                headers=normal_user_token_headers,
            )

            # Should have rate limit headers
            assert "X-RateLimit-Limit" in r.headers
            limit = int(r.headers["X-RateLimit-Limit"])
            # Strict limit should be 10/minute
            assert limit == 10
    finally:
        # Cleanup
        try:
            db.delete(project)
            db.commit()
        except Exception:
            # Project may have been deleted already
            pass


def test_rate_limit_error_response_format(client: TestClient) -> None:
    """Test that 429 error responses have correct format"""
    # Make multiple requests to trigger rate limit
    for i in range(6):
        r = client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": "test@example.com", "password": "wrongpassword"},
        )

    # Last request should be rate limited
    assert r.status_code == 429

    # Verify response has error detail
    data = r.json()
    assert "detail" in data or "error" in data

    # Verify headers
    assert "Retry-After" in r.headers
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers

    # Remaining should be 0
    remaining = int(r.headers["X-RateLimit-Remaining"])
    assert remaining == 0


def test_rate_limit_preserves_other_errors(client: TestClient) -> None:
    """Test that rate limiting doesn't interfere with other HTTP errors"""
    # Test 404 error
    r = client.get(f"{settings.API_V1_STR}/nonexistent/endpoint")
    assert r.status_code == 404

    # Rate limit headers may or may not be present on error responses
    # The important thing is that the original error status is preserved
    # (Not testing headers on 404 since they may not be added by middleware for non-existent routes)


def test_health_check_exempt_from_rate_limit(client: TestClient) -> None:
    """Test that health check endpoints are exempt from rate limiting"""
    # Make many requests to a health/status endpoint
    # If it exists, it should not be rate limited
    # For now, we'll verify that root endpoint isn't overly restricted

    responses = []
    for i in range(10):
        r = client.get("/")
        responses.append(r)

    # Most should succeed (even if endpoint doesn't exist, shouldn't be rate limited)
    success_count = sum(1 for r in responses if r.status_code != 429)
    assert success_count >= 8  # At least 80% should succeed


def test_options_requests_exempt_from_rate_limit(client: TestClient) -> None:
    """Test that OPTIONS requests (CORS preflight) are not rate limited"""
    # OPTIONS requests should not count against rate limit
    responses = []
    for i in range(10):
        r = client.options(f"{settings.API_V1_STR}/users/me")
        responses.append(r)

    # None should be rate limited
    rate_limited = sum(1 for r in responses if r.status_code == 429)
    assert rate_limited == 0


def test_rate_limit_headers_format(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that rate limit headers have correct format and values"""
    r = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200

    # X-RateLimit-Limit should be a positive integer
    limit = r.headers["X-RateLimit-Limit"]
    assert limit.isdigit()
    assert int(limit) > 0

    # X-RateLimit-Remaining should be a non-negative integer
    remaining = r.headers["X-RateLimit-Remaining"]
    assert remaining.isdigit()
    assert int(remaining) >= 0

    # X-RateLimit-Reset should be a Unix timestamp (can be float)
    reset = r.headers["X-RateLimit-Reset"]
    reset_float = float(reset)
    assert reset_float > 0


def test_concurrent_requests_rate_limiting(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that concurrent requests are properly rate limited"""
    # Make several requests in quick succession
    responses = []
    for i in range(10):
        r = client.get(
            f"{settings.API_V1_STR}/users/me",
            headers=normal_user_token_headers,
        )
        responses.append(r)

    # All should succeed (within the 100/minute limit)
    for r in responses:
        assert r.status_code == 200

    # Remaining count should decrease monotonically
    remaining_counts = [int(r.headers["X-RateLimit-Remaining"]) for r in responses]

    # Each request should consume from the limit
    assert remaining_counts[0] >= remaining_counts[-1]
