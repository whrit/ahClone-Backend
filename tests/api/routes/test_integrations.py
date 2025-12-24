"""Tests for integrations API routes - TDD approach"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.oauth.google import GoogleOAuthClient
from app.models import User
from app.models.integration import IntegrationAccount


def test_start_google_oauth_returns_auth_url_and_state(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that start_google_oauth returns authorization URL and state for valid service"""
    # Test for GSC
    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/connect?service=gsc",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "authorization_url" in data
    assert "state" in data
    assert isinstance(data["authorization_url"], str)
    assert isinstance(data["state"], str)
    assert "https://accounts.google.com" in data["authorization_url"]
    assert len(data["state"]) > 0

    # Test for Ads
    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/connect?service=ads",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "authorization_url" in data
    assert "state" in data


def test_start_google_oauth_validates_service_parameter(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test that start_google_oauth returns 422 for invalid service parameter"""
    # Invalid service
    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/connect?service=invalid",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 422

    # Missing service parameter
    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/connect",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 422


def test_google_oauth_callback_with_invalid_state_returns_400(
    client: TestClient,
) -> None:
    """Test that google_oauth_callback returns 400 for invalid/missing state"""
    # Invalid state
    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/callback?code=test_code&state=invalid_state"
    )
    assert r.status_code == 400
    data = r.json()
    assert "detail" in data
    assert "Invalid" in data["detail"] or "state" in data["detail"].lower()


@pytest.mark.asyncio
async def test_google_oauth_callback_success(
    client: TestClient, normal_user: User, db: Session
) -> None:
    """Test successful OAuth callback flow with mocked Google API calls"""
    # Clean up any existing integrations first
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id,
        IntegrationAccount.provider == "google_gsc",
    )
    existing = db.exec(statement).first()
    if existing:
        db.delete(existing)
        db.commit()

    # First, start the OAuth flow to get a valid state
    from app.api.routes.integrations import _oauth_states

    state = "test_state_123"
    user_id = str(normal_user.id)

    # Manually add state to in-memory store
    _oauth_states[state] = {
        "user_id": user_id,
        "service": "gsc",
        "created_at": datetime.now(timezone.utc),
    }

    # Mock the OAuth client methods
    with patch("app.api.routes.integrations.GoogleOAuthClient") as mock_oauth_class:
        mock_oauth_instance = MagicMock()
        mock_oauth_class.return_value = mock_oauth_instance

        # Mock exchange_code
        mock_oauth_instance.exchange_code = AsyncMock(
            return_value={
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
            }
        )

        # Mock get_user_info
        mock_oauth_instance.get_user_info = AsyncMock(
            return_value={
                "email": "test@example.com",
                "verified_email": True,
            }
        )

        # Mock encrypt_token
        mock_oauth_instance.encrypt_token = MagicMock(
            side_effect=lambda token: f"encrypted_{token}"
        )

        # Make the callback request (without following redirects)
        r = client.get(
            f"{settings.API_V1_STR}/integrations/google/callback?code=test_code&state={state}",
            follow_redirects=False,
        )

        # Should redirect to frontend success page
        assert r.status_code == 307  # Redirect
        assert "location" in r.headers
        assert "success" in r.headers["location"].lower()

    # Verify integration account was created in database
    db.expire_all()  # Clear SQLModel cache
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id,
        IntegrationAccount.provider == "google_gsc",
    )
    integration = db.exec(statement).first()
    assert integration is not None
    assert integration.account_email == "test@example.com"
    assert integration.access_token_encrypted.startswith("encrypted_")

    # Cleanup
    if integration:
        db.delete(integration)
        db.commit()


def test_get_google_integration_status_when_not_connected(
    client: TestClient, normal_user_token_headers: dict[str, str], normal_user: User, db: Session
) -> None:
    """Test get_google_integration_status returns false when no integrations exist"""
    # Clean up any existing integrations first
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id
    )
    existing_accounts = db.exec(statement).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/status",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "gsc_connected" in data
    assert "ads_connected" in data
    assert data["gsc_connected"] is False
    assert data["ads_connected"] is False
    assert data.get("gsc_email") is None
    assert data.get("ads_email") is None


def test_get_google_integration_status_when_connected(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    normal_user: User,
    db: Session,
) -> None:
    """Test get_google_integration_status returns true when integrations exist"""
    # Clean up any existing integrations first
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id
    )
    existing_accounts = db.exec(statement).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    # Create a GSC integration account
    oauth_client = GoogleOAuthClient()
    gsc_account = IntegrationAccount(
        user_id=normal_user.id,
        provider="google_gsc",
        access_token_encrypted=oauth_client.encrypt_token("test_access_token"),
        refresh_token_encrypted=oauth_client.encrypt_token("test_refresh_token"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        account_email="gsc@example.com",
    )
    db.add(gsc_account)
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/integrations/google/status",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["gsc_connected"] is True
    assert data["ads_connected"] is False
    assert data["gsc_email"] == "gsc@example.com"
    assert data.get("ads_email") is None

    # Cleanup
    db.delete(gsc_account)
    db.commit()


def test_disconnect_google_integration_removes_account(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    normal_user: User,
    db: Session,
) -> None:
    """Test disconnect_google_integration removes the integration account"""
    # Clean up any existing integrations first
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id
    )
    existing_accounts = db.exec(statement).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    # Create a GSC integration account
    oauth_client = GoogleOAuthClient()
    gsc_account = IntegrationAccount(
        user_id=normal_user.id,
        provider="google_gsc",
        access_token_encrypted=oauth_client.encrypt_token("test_access_token"),
        refresh_token_encrypted=oauth_client.encrypt_token("test_refresh_token"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        account_email="gsc@example.com",
    )
    db.add(gsc_account)
    db.commit()
    db.refresh(gsc_account)

    # Disconnect
    r = client.delete(
        f"{settings.API_V1_STR}/integrations/google/gsc",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "message" in data
    assert "Disconnected" in data["message"]

    # Verify account is deleted
    db.expire_all()  # Clear SQLModel cache
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id,
        IntegrationAccount.provider == "google_gsc",
    )
    integration = db.exec(statement).first()
    assert integration is None


def test_disconnect_google_integration_when_not_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], normal_user: User, db: Session
) -> None:
    """Test disconnect_google_integration returns 404 when integration doesn't exist"""
    # Clean up any existing integrations first to ensure clean state
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == normal_user.id
    )
    existing_accounts = db.exec(statement).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    r = client.delete(
        f"{settings.API_V1_STR}/integrations/google/gsc",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404
    data = r.json()
    assert "detail" in data
