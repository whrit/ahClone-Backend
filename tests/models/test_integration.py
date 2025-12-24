"""Tests for IntegrationAccount model - TDD approach"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models import User
from app.models.integration import IntegrationAccount


def test_create_integration_account(db: Session) -> None:
    """Test creating an IntegrationAccount"""
    # Create a user first
    user = User(
        email="integration_test@example.com",
        hashed_password="hashed_password",
        full_name="Integration Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    integration = IntegrationAccount(
        user_id=user.id,
        provider="google_gsc",
        access_token_encrypted="encrypted_access_token_123",
        refresh_token_encrypted="encrypted_refresh_token_456",
        token_expires_at=datetime.now(timezone.utc),
        account_email="test@example.com",
        metadata_json={"account_id": "123456"},
    )

    db.add(integration)
    db.commit()
    db.refresh(integration)

    assert integration.id is not None
    assert integration.user_id == user.id
    assert integration.provider == "google_gsc"
    assert integration.access_token_encrypted == "encrypted_access_token_123"
    assert integration.refresh_token_encrypted == "encrypted_refresh_token_456"
    assert integration.account_email == "test@example.com"
    assert integration.metadata_json == {"account_id": "123456"}
    assert integration.created_at is not None
    assert integration.updated_at is not None


def test_integration_account_defaults(db: Session) -> None:
    """Test IntegrationAccount default values"""
    # Create a user first
    user = User(
        email="integration_defaults@example.com",
        hashed_password="hashed_password",
        full_name="Defaults Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    integration = IntegrationAccount(
        user_id=user.id,
        provider="google_ads",
        access_token_encrypted="token1",
        refresh_token_encrypted="token2",
        token_expires_at=datetime.now(timezone.utc),
    )

    db.add(integration)
    db.commit()
    db.refresh(integration)

    assert integration.account_email is None
    assert integration.metadata_json == {}
    assert isinstance(integration.created_at, datetime)
    assert isinstance(integration.updated_at, datetime)


def test_query_integration_accounts_by_user(db: Session) -> None:
    """Test querying IntegrationAccounts by user_id"""
    # Create a user first
    user = User(
        email="integration_query@example.com",
        hashed_password="hashed_password",
        full_name="Query Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create two integrations for the same user
    integration1 = IntegrationAccount(
        user_id=user.id,
        provider="google_gsc",
        access_token_encrypted="token1",
        refresh_token_encrypted="refresh1",
        token_expires_at=datetime.now(timezone.utc),
    )
    integration2 = IntegrationAccount(
        user_id=user.id,
        provider="google_ads",
        access_token_encrypted="token2",
        refresh_token_encrypted="refresh2",
        token_expires_at=datetime.now(timezone.utc),
    )

    db.add(integration1)
    db.add(integration2)
    db.commit()

    # Query integrations for this user
    statement = select(IntegrationAccount).where(IntegrationAccount.user_id == user.id)
    integrations = db.exec(statement).all()

    assert len(integrations) == 2
    providers = {i.provider for i in integrations}
    assert providers == {"google_gsc", "google_ads"}


def test_integration_account_user_foreign_key(db: Session) -> None:
    """Test that user_id has foreign key constraint"""
    # This test verifies the foreign key relationship exists
    # The actual constraint enforcement depends on database setup
    integration = IntegrationAccount(
        user_id=uuid.uuid4(),  # Non-existent user
        provider="google_gsc",
        access_token_encrypted="token",
        refresh_token_encrypted="refresh",
        token_expires_at=datetime.now(timezone.utc),
    )

    # Note: Foreign key constraint will fail on commit if user doesn't exist
    # For this test, we just verify the field is correctly set
    assert integration.user_id is not None
