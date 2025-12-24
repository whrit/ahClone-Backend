"""Integration models for OAuth and external service connections."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import EmailStr
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class IntegrationAccount(SQLModel, table=True):
    """Stores OAuth tokens for external integrations"""

    __tablename__ = "integration_accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    provider: str  # "google_gsc", "google_ads"

    # Encrypted tokens
    access_token_encrypted: str
    refresh_token_encrypted: str
    token_expires_at: datetime

    # Account info
    account_email: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
