"""Google OAuth 2.0 client for GSC and Ads APIs."""
from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet

from app.core.config import settings


class GoogleOAuthClient:
    """Google OAuth 2.0 client for GSC and Ads APIs"""

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
    ADS_SCOPES = ["https://www.googleapis.com/auth/adwords"]

    def __init__(self) -> None:
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        # Initialize Fernet with TOKEN_ENCRYPTION_KEY
        self._fernet: Fernet | None = None
        if settings.TOKEN_ENCRYPTION_KEY:
            self._fernet = Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())

    def get_authorization_url(
        self, scopes: list[str], state: str | None = None
    ) -> tuple[str, str]:
        """
        Generate OAuth authorization URL.

        Args:
            scopes: List of OAuth scopes to request
            state: Optional state parameter for CSRF protection

        Returns:
            Tuple of (authorization_url, state)
        """
        if state is None:
            state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }

        url = f"{self.AUTHORIZATION_URL}?{urlencode(params)}"
        return url, state

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for tokens using httpx.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Dictionary containing access_token, refresh_token, expires_in, etc.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails
        """
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh an access token.

        Args:
            refresh_token: The refresh token to use

        Returns:
            Dictionary containing new access_token, expires_in, etc.

        Raises:
            httpx.HTTPStatusError: If the token refresh fails
        """
        data = {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """
        Get Google user info.

        Args:
            access_token: Valid access token

        Returns:
            Dictionary containing user info (email, name, etc.)

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(self.USERINFO_URL, headers=headers)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    def encrypt_token(self, token: str) -> str:
        """
        Encrypt token for storage using Fernet.

        Args:
            token: Plain text token to encrypt

        Returns:
            Encrypted token as string

        Raises:
            RuntimeError: If encryption key is not configured
        """
        if not self._fernet:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY not configured")

        encrypted_bytes = self._fernet.encrypt(token.encode())
        return encrypted_bytes.decode()

    def decrypt_token(self, encrypted: str) -> str:
        """
        Decrypt stored token.

        Args:
            encrypted: Encrypted token string

        Returns:
            Decrypted plain text token

        Raises:
            RuntimeError: If encryption key is not configured
        """
        if not self._fernet:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY not configured")

        decrypted_bytes = self._fernet.decrypt(encrypted.encode())
        return decrypted_bytes.decode()
