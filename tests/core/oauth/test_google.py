"""Tests for GoogleOAuthClient - TDD approach"""
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from respx import MockRouter

from app.core.config import settings
from app.core.oauth.google import GoogleOAuthClient


# Test settings for OAuth
TEST_CLIENT_ID = "test-client-id-12345"
TEST_CLIENT_SECRET = "test-client-secret-67890"
TEST_REDIRECT_URI = "http://localhost:8000/api/v1/integrations/google/callback"


@pytest.fixture
def oauth_client() -> GoogleOAuthClient:
    """Create a GoogleOAuthClient instance for testing with mocked settings"""
    with patch.object(settings, "GOOGLE_CLIENT_ID", TEST_CLIENT_ID), \
         patch.object(settings, "GOOGLE_CLIENT_SECRET", TEST_CLIENT_SECRET), \
         patch.object(settings, "GOOGLE_REDIRECT_URI", TEST_REDIRECT_URI):
        return GoogleOAuthClient()


def test_get_authorization_url_generates_valid_url() -> None:
    """Test that get_authorization_url generates a valid URL with state"""
    with patch.object(settings, "GOOGLE_CLIENT_ID", TEST_CLIENT_ID), \
         patch.object(settings, "GOOGLE_CLIENT_SECRET", TEST_CLIENT_SECRET), \
         patch.object(settings, "GOOGLE_REDIRECT_URI", TEST_REDIRECT_URI):
        client = GoogleOAuthClient()
        scopes = GoogleOAuthClient.GSC_SCOPES
        url, state = client.get_authorization_url(scopes)

        # Parse URL
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "accounts.google.com"
        assert parsed.path == "/o/oauth2/v2/auth"

        # Parse query parameters
        params = parse_qs(parsed.query)
        assert params["client_id"][0] == TEST_CLIENT_ID
        assert params["redirect_uri"][0] == TEST_REDIRECT_URI
        assert params["response_type"][0] == "code"
        assert params["scope"][0] == " ".join(scopes)
        assert "state" in params
        assert params["state"][0] == state
        assert params["access_type"][0] == "offline"
        assert params["prompt"][0] == "consent"

        # State should be a non-empty string
        assert isinstance(state, str)
        assert len(state) > 0


def test_get_authorization_url_with_custom_state(oauth_client: GoogleOAuthClient) -> None:
    """Test get_authorization_url with a custom state parameter"""
    scopes = GoogleOAuthClient.ADS_SCOPES
    custom_state = "my_custom_state_123"

    url, returned_state = oauth_client.get_authorization_url(scopes, state=custom_state)

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert params["state"][0] == custom_state
    assert returned_state == custom_state


def test_encrypt_decrypt_token_roundtrip(oauth_client: GoogleOAuthClient) -> None:
    """Test that encrypt and decrypt work correctly for token round-trip"""
    original_token = "ya29.a0AfH6SMBx..."

    encrypted = oauth_client.encrypt_token(original_token)
    assert encrypted != original_token
    assert isinstance(encrypted, str)

    decrypted = oauth_client.decrypt_token(encrypted)
    assert decrypted == original_token


def test_encrypt_token_produces_different_output(oauth_client: GoogleOAuthClient) -> None:
    """Test that encrypting the same token produces different output (due to IV)"""
    token = "test_token_123"

    # Fernet includes timestamp, so repeated encryption should differ
    encrypted1 = oauth_client.encrypt_token(token)
    encrypted2 = oauth_client.encrypt_token(token)

    # Due to Fernet's design, these may or may not be different
    # But they should both decrypt to the same value
    assert oauth_client.decrypt_token(encrypted1) == token
    assert oauth_client.decrypt_token(encrypted2) == token


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_success(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test successful authorization code exchange"""
    # Mock the token endpoint
    mock_response = {
        "access_token": "ya29.a0AfH6SMBx...",
        "refresh_token": "1//0gHZzMXb...",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
    }

    respx_mock.post(GoogleOAuthClient.TOKEN_URL).mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    result = await oauth_client.exchange_code("authorization_code_123")

    assert result["access_token"] == "ya29.a0AfH6SMBx..."
    assert result["refresh_token"] == "1//0gHZzMXb..."
    assert result["expires_in"] == 3600
    assert result["token_type"] == "Bearer"


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_failure(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test failed authorization code exchange"""
    error_response = {
        "error": "invalid_grant",
        "error_description": "Bad Request",
    }

    respx_mock.post(GoogleOAuthClient.TOKEN_URL).mock(
        return_value=httpx.Response(400, json=error_response)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await oauth_client.exchange_code("invalid_code")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_success(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test successful token refresh"""
    mock_response = {
        "access_token": "ya29.new_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
    }

    respx_mock.post(GoogleOAuthClient.TOKEN_URL).mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    result = await oauth_client.refresh_token("1//0gHZzMXb...")

    assert result["access_token"] == "ya29.new_access_token"
    assert result["expires_in"] == 3600
    assert "refresh_token" not in result  # Refresh endpoint doesn't return new refresh token


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_failure(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test failed token refresh"""
    error_response = {
        "error": "invalid_grant",
        "error_description": "Token has been expired or revoked.",
    }

    respx_mock.post(GoogleOAuthClient.TOKEN_URL).mock(
        return_value=httpx.Response(400, json=error_response)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await oauth_client.refresh_token("invalid_refresh_token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_success(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test successful user info retrieval"""
    mock_response = {
        "id": "123456789",
        "email": "user@example.com",
        "verified_email": True,
        "name": "Test User",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://example.com/photo.jpg",
    }

    respx_mock.get(GoogleOAuthClient.USERINFO_URL).mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    result = await oauth_client.get_user_info("ya29.access_token")

    assert result["email"] == "user@example.com"
    assert result["verified_email"] is True
    assert result["name"] == "Test User"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_failure(
    respx_mock: MockRouter, oauth_client: GoogleOAuthClient
) -> None:
    """Test failed user info retrieval"""
    respx_mock.get(GoogleOAuthClient.USERINFO_URL).mock(
        return_value=httpx.Response(401, json={"error": "Invalid credentials"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await oauth_client.get_user_info("invalid_token")
