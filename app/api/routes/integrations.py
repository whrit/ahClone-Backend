"""Integration API routes for OAuth and external service connections."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.oauth.google import GoogleOAuthClient
from app.models.integration import IntegrationAccount

router = APIRouter(prefix="/integrations", tags=["integrations"])

# In-memory OAuth state storage (use Redis in production)
_oauth_states: dict[str, dict[str, Any]] = {}


@router.get("/google/connect")
async def start_google_oauth(
    current_user: CurrentUser,
    service: str = Query(..., pattern="^(gsc|ads)$"),
) -> dict[str, str]:
    """
    Start Google OAuth flow for GSC or Ads.
    Returns {authorization_url, state}
    """
    oauth_client = GoogleOAuthClient()

    # Determine scopes based on service
    if service == "gsc":
        scopes = GoogleOAuthClient.GSC_SCOPES
    else:  # ads
        scopes = GoogleOAuthClient.ADS_SCOPES

    # Generate authorization URL with state
    authorization_url, state = oauth_client.get_authorization_url(scopes)

    # Store state with user_id and service for validation in callback
    _oauth_states[state] = {
        "user_id": str(current_user.id),
        "service": service,
        "created_at": datetime.now(timezone.utc),
    }

    return {
        "authorization_url": authorization_url,
        "state": state,
    }


@router.get("/google/callback")
async def google_oauth_callback(
    session: SessionDep,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """
    Handle Google OAuth callback.
    - Validate state
    - Exchange code for tokens
    - Get user info
    - Store/update IntegrationAccount
    - Redirect to frontend success page
    """
    # Validate state
    state_data = _oauth_states.get(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    # Remove used state
    del _oauth_states[state]

    # Check state expiry (5 minutes)
    created_at = state_data["created_at"]
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="State parameter has expired")

    user_id = uuid.UUID(state_data["user_id"])
    service = state_data["service"]

    oauth_client = GoogleOAuthClient()

    try:
        # Exchange code for tokens
        token_data = await oauth_client.exchange_code(code)

        # Get user info
        user_info = await oauth_client.get_user_info(token_data["access_token"])

        # Encrypt tokens
        access_token_encrypted = oauth_client.encrypt_token(token_data["access_token"])
        refresh_token_encrypted = oauth_client.encrypt_token(token_data["refresh_token"])

        # Calculate token expiry
        token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data["expires_in"]
        )

        # Determine provider name
        provider = f"google_{service}"

        # Check if integration account already exists
        statement = select(IntegrationAccount).where(
            IntegrationAccount.user_id == user_id,
            IntegrationAccount.provider == provider,
        )
        existing_account = session.exec(statement).first()

        if existing_account:
            # Update existing account
            existing_account.access_token_encrypted = access_token_encrypted
            existing_account.refresh_token_encrypted = refresh_token_encrypted
            existing_account.token_expires_at = token_expires_at
            existing_account.account_email = user_info.get("email")
            existing_account.updated_at = datetime.now(timezone.utc)
            session.add(existing_account)
        else:
            # Create new integration account
            new_account = IntegrationAccount(
                user_id=user_id,
                provider=provider,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                token_expires_at=token_expires_at,
                account_email=user_info.get("email"),
            )
            session.add(new_account)

        session.commit()

        # Redirect to frontend success page
        frontend_url = f"{settings.FRONTEND_HOST}/integrations/success?service={service}"
        return RedirectResponse(url=frontend_url, status_code=307)

    except Exception as e:
        # Redirect to frontend error page with error message
        error_message = str(e)
        frontend_url = f"{settings.FRONTEND_HOST}/integrations/error?message={error_message}"
        return RedirectResponse(url=frontend_url, status_code=307)


@router.get("/google/status")
async def get_google_integration_status(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, bool | str | None]:
    """
    Check Google integration status.
    Returns {gsc_connected, ads_connected, gsc_email, ads_email}
    """
    # Check GSC integration
    gsc_statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == current_user.id,
        IntegrationAccount.provider == "google_gsc",
    )
    gsc_account = session.exec(gsc_statement).first()

    # Check Ads integration
    ads_statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == current_user.id,
        IntegrationAccount.provider == "google_ads",
    )
    ads_account = session.exec(ads_statement).first()

    return {
        "gsc_connected": gsc_account is not None,
        "ads_connected": ads_account is not None,
        "gsc_email": gsc_account.account_email if gsc_account else None,
        "ads_email": ads_account.account_email if ads_account else None,
    }


@router.delete("/google/{service}")
async def disconnect_google_integration(
    session: SessionDep,
    current_user: CurrentUser,
    service: str,
) -> dict[str, str]:
    """Disconnect a Google integration. Returns {message: "Disconnected"}"""
    # Validate service parameter
    if service not in ["gsc", "ads"]:
        raise HTTPException(status_code=400, detail="Invalid service parameter")

    provider = f"google_{service}"

    # Find integration account
    statement = select(IntegrationAccount).where(
        IntegrationAccount.user_id == current_user.id,
        IntegrationAccount.provider == provider,
    )
    account = session.exec(statement).first()

    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"No {service.upper()} integration found for this user",
        )

    # Delete the account
    session.delete(account)
    session.commit()

    return {"message": f"Disconnected {service.upper()} integration"}
