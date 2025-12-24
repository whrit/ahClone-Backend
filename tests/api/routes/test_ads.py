"""Tests for Ads API routes."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User
from app.models.ads import (
    AdsCampaignDaily,
    AdsAccount,
    AdsKeywordDaily,
)
from app.models.gsc import GSCQueryDaily
from app.models.integration import IntegrationAccount
from app.models.project import Project
from tests.utils.project import create_random_project


@pytest.fixture
def project_with_ads(db: Session, normal_user: User) -> Project:
    """Create a project with linked Ads account."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create Ads account for the project
    ads_account = AdsAccount(
        project_id=project.id,
        customer_id="1234567890",
        descriptive_name="Test Ads Account",
        currency_code="USD",
        linked_at=datetime.now(timezone.utc),
        last_sync_at=datetime.now(timezone.utc) - timedelta(hours=1),
        sync_status="completed",
    )
    db.add(ads_account)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def integration_account_ads(db: Session, normal_user: User) -> IntegrationAccount:
    """Create a Google Ads integration account for the user."""
    from app.core.oauth.google import GoogleOAuthClient

    oauth_client = GoogleOAuthClient()
    account = IntegrationAccount(
        user_id=normal_user.id,
        provider="google_ads",
        access_token_encrypted=oauth_client.encrypt_token("test_access_token"),
        refresh_token_encrypted=oauth_client.encrypt_token("test_refresh_token"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        account_email="test@example.com",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture
def ads_campaign_data(db: Session, project_with_ads: Project) -> list[AdsCampaignDaily]:
    """Create sample Ads campaign data."""
    today = date.today()
    campaigns = []

    campaign_configs = [
        {
            "campaign_id": "111",
            "campaign_name": "Brand Campaign",
            "campaign_status": "ENABLED",
            "impressions": 10000,
            "clicks": 500,
            "cost_micros": 50000000,  # $50
            "conversions": 25.0,
            "conversion_value": 1250.0,
        },
        {
            "campaign_id": "222",
            "campaign_name": "Generic Campaign",
            "campaign_status": "ENABLED",
            "impressions": 5000,
            "clicks": 200,
            "cost_micros": 30000000,  # $30
            "conversions": 10.0,
            "conversion_value": 500.0,
        },
    ]

    for config in campaign_configs:
        for days_ago in range(7):
            campaign_daily = AdsCampaignDaily(
                project_id=project_with_ads.id,
                date=today - timedelta(days=days_ago),
                campaign_id=config["campaign_id"],
                campaign_name=config["campaign_name"],
                campaign_status=config["campaign_status"],
                impressions=config["impressions"],
                clicks=config["clicks"],
                cost_micros=config["cost_micros"],
                conversions=config["conversions"],
                conversion_value=config["conversion_value"],
            )
            db.add(campaign_daily)
            campaigns.append(campaign_daily)

    db.commit()
    return campaigns


@pytest.fixture
def ads_keyword_data(db: Session, project_with_ads: Project) -> list[AdsKeywordDaily]:
    """Create sample Ads keyword data."""
    today = date.today()
    keywords = []

    keyword_configs = [
        {
            "campaign_id": "111",
            "ad_group_id": "aaa",
            "criterion_id": "1001",
            "keyword_text": "seo tools",
            "match_type": "EXACT",
            "impressions": 1000,
            "clicks": 50,
            "cost_micros": 5000000,  # $5
            "conversions": 2.5,
            "average_cpc_micros": 100000,  # $0.10
            "quality_score": 8,
            "final_url": "https://example.com/seo-tools",
        },
        {
            "campaign_id": "111",
            "ad_group_id": "aaa",
            "criterion_id": "1002",
            "keyword_text": "keyword research",
            "match_type": "PHRASE",
            "impressions": 800,
            "clicks": 40,
            "cost_micros": 4000000,  # $4
            "conversions": 2.0,
            "average_cpc_micros": 100000,  # $0.10
            "quality_score": 7,
            "final_url": "https://example.com/keyword-research",
        },
    ]

    for config in keyword_configs:
        for days_ago in range(7):
            keyword_daily = AdsKeywordDaily(
                project_id=project_with_ads.id,
                date=today - timedelta(days=days_ago),
                campaign_id=config["campaign_id"],
                ad_group_id=config["ad_group_id"],
                criterion_id=config["criterion_id"],
                keyword_text=config["keyword_text"],
                match_type=config["match_type"],
                impressions=config["impressions"],
                clicks=config["clicks"],
                cost_micros=config["cost_micros"],
                conversions=config["conversions"],
                average_cpc_micros=config["average_cpc_micros"],
                quality_score=config["quality_score"],
                final_url=config["final_url"],
            )
            db.add(keyword_daily)
            keywords.append(keyword_daily)

    db.commit()
    return keywords


@pytest.fixture
def gsc_query_data_for_overlap(
    db: Session, project_with_ads: Project
) -> list[GSCQueryDaily]:
    """Create sample GSC query data for overlap testing."""
    today = date.today()
    queries = []

    query_configs = [
        # Overlapping keyword with paid
        {
            "query": "seo tools",
            "clicks": 100,
            "impressions": 2000,
            "ctr": 0.05,
            "position": 3.0,
        },
        # Organic only
        {
            "query": "content marketing",
            "clicks": 80,
            "impressions": 1500,
            "ctr": 0.053,
            "position": 5.0,
        },
    ]

    for config in query_configs:
        for days_ago in range(7):
            query_daily = GSCQueryDaily(
                project_id=project_with_ads.id,
                date=today - timedelta(days=days_ago),
                query=config["query"],
                page="https://example.com/blog",
                country="USA",
                device="DESKTOP",
                clicks=config["clicks"],
                impressions=config["impressions"],
                ctr=config["ctr"],
                position=config["position"],
            )
            db.add(query_daily)
            queries.append(query_daily)

    db.commit()
    return queries


# ==================== Test list_available_accounts ====================


def test_list_available_accounts(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
    integration_account_ads: IntegrationAccount,
) -> None:
    """Test listing available Google Ads accounts."""
    project = create_random_project(db, owner_id=normal_user.id)

    mock_accounts = [
        {
            "customer_id": "1234567890",
            "name": "Main Account",
            "currency": "USD",
            "timezone": "America/New_York",
        },
        {
            "customer_id": "0987654321",
            "name": "Secondary Account",
            "currency": "EUR",
            "timezone": "Europe/London",
        },
    ]

    with patch("app.api.routes.ads.GoogleAdsService") as mock_service:
        mock_instance = MagicMock()
        mock_instance.list_accessible_customers.return_value = mock_accounts
        mock_service.return_value = mock_instance

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/ads/accounts",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["customer_id"] == "1234567890"
        assert data[0]["name"] == "Main Account"


def test_list_available_accounts_no_integration(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test listing accounts fails without integration account."""
    # Delete any existing integration accounts for this user
    stmt = select(IntegrationAccount).where(IntegrationAccount.user_id == normal_user.id)
    existing_accounts = db.exec(stmt).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/accounts",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "Integration account not found" in response.json()["detail"]


def test_list_available_accounts_unauthorized(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test listing accounts for another user's project fails."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{other_project.id}/ads/accounts",
        headers=normal_user_token_headers,
    )

    assert response.status_code in [403, 400]


# ==================== Test link_ads_account ====================


def test_link_ads_account(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
    integration_account_ads: IntegrationAccount,
) -> None:
    """Test linking a Google Ads account to a project."""
    project = create_random_project(db, owner_id=normal_user.id)

    mock_customer_details = {
        "customer_id": "1234567890",
        "name": "Main Account",
        "currency": "USD",
        "timezone": "America/New_York",
    }

    with patch("app.api.routes.ads.GoogleAdsService") as mock_service:
        mock_instance = MagicMock()
        mock_instance._get_customer_details.return_value = mock_customer_details
        mock_service.return_value = mock_instance

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/ads/link",
            headers=normal_user_token_headers,
            json={"customer_id": "1234567890"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["customer_id"] == "1234567890"
        assert data["descriptive_name"] == "Main Account"
        assert data["currency_code"] == "USD"
        assert data["project_id"] == str(project.id)

        # Verify in database
        statement = select(AdsAccount).where(AdsAccount.project_id == project.id)
        ads_account = db.exec(statement).first()
        assert ads_account is not None
        assert ads_account.customer_id == "1234567890"


def test_link_ads_account_already_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    integration_account_ads: IntegrationAccount,
) -> None:
    """Test linking an ads account that is already linked fails."""
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/link",
        headers=normal_user_token_headers,
        json={"customer_id": "0987654321"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "already" in detail and "linked" in detail


def test_link_ads_account_no_integration(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test linking ads account fails without integration account."""
    # Delete any existing integration accounts for this user
    stmt = select(IntegrationAccount).where(IntegrationAccount.user_id == normal_user.id)
    existing_accounts = db.exec(stmt).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    project = create_random_project(db, owner_id=normal_user.id)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/link",
        headers=normal_user_token_headers,
        json={"customer_id": "1234567890"},
    )

    assert response.status_code == 404
    assert "Integration account not found" in response.json()["detail"]


# ==================== Test trigger_sync ====================


def test_trigger_sync(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
) -> None:
    """Test triggering a manual Ads sync."""
    with patch("app.api.routes.ads.sync_ads_account") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-123")

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/sync",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Sync task queued"
        assert data["task_id"] == "task-123"

        # Verify task was called with correct project_id
        mock_task.delay.assert_called_once_with(str(project_with_ads.id))


def test_trigger_sync_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test triggering sync for project without Ads account fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/sync",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 400
    assert "No ads account linked" in response.json()["detail"]


# ==================== Test get_campaigns ====================


def test_get_campaigns(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_campaign_data: list[AdsCampaignDaily],
) -> None:
    """Test retrieving campaign performance data."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/campaigns",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "total" in data
    assert isinstance(data["data"], list)
    assert data["total"] > 0

    # Verify data structure
    if len(data["data"]) > 0:
        first_campaign = data["data"][0]
        assert "campaign_id" in first_campaign
        assert "campaign_name" in first_campaign
        assert "campaign_status" in first_campaign
        assert "impressions" in first_campaign
        assert "clicks" in first_campaign
        assert "cost_micros" in first_campaign
        assert "conversions" in first_campaign
        assert "conversion_value" in first_campaign


def test_get_campaigns_with_period(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_campaign_data: list[AdsCampaignDaily],
) -> None:
    """Test retrieving campaigns with custom period."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/campaigns?period_days=14",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data


def test_get_campaigns_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test retrieving campaigns for project without Ads account fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/campaigns",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 400
    assert "No ads account linked" in response.json()["detail"]


def test_get_campaigns_no_data(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
) -> None:
    """Test retrieving campaigns when no data exists."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/campaigns",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    # Should return empty data, not an error
    assert "data" in data
    assert "total" in data


# ==================== Test get_keywords (BONUS) ====================


def test_get_keywords(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_keyword_data: list[AdsKeywordDaily],
) -> None:
    """Test retrieving keyword performance data."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/keywords",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "total" in data
    assert isinstance(data["data"], list)

    # Verify data structure
    if len(data["data"]) > 0:
        first_keyword = data["data"][0]
        assert "keyword_text" in first_keyword
        assert "match_type" in first_keyword
        assert "impressions" in first_keyword
        assert "clicks" in first_keyword
        assert "cost_micros" in first_keyword
        assert "conversions" in first_keyword
        assert "average_cpc_micros" in first_keyword


def test_get_keywords_with_search(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_keyword_data: list[AdsKeywordDaily],
) -> None:
    """Test retrieving keywords with search filter."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/keywords?search=seo",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()

    # All returned keywords should contain "seo"
    for keyword_row in data["data"]:
        assert "seo" in keyword_row["keyword_text"].lower()


def test_get_keywords_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test retrieving keywords for project without Ads account fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/keywords",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 400
    assert "No ads account linked" in response.json()["detail"]


# ==================== Test get_seo_overlap ====================


def test_get_seo_overlap(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_keyword_data: list[AdsKeywordDaily],
    gsc_query_data_for_overlap: list[GSCQueryDaily],
) -> None:
    """Test retrieving SEO + PPC overlap analysis."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/seo-overlap",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "total" in data
    assert isinstance(data["data"], list)

    # Verify data structure
    if len(data["data"]) > 0:
        first_overlap = data["data"][0]
        assert "keyword" in first_overlap
        assert "organic_position" in first_overlap
        assert "paid_position" in first_overlap
        assert "organic_clicks" in first_overlap
        assert "paid_clicks" in first_overlap
        assert "total_clicks" in first_overlap


def test_get_seo_overlap_with_period(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
    ads_keyword_data: list[AdsKeywordDaily],
    gsc_query_data_for_overlap: list[GSCQueryDaily],
) -> None:
    """Test retrieving overlap with custom period."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/seo-overlap?period_days=14",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data


def test_get_seo_overlap_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test retrieving overlap for project without Ads account fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/ads/seo-overlap",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 400
    assert "No ads account linked" in response.json()["detail"]


def test_get_seo_overlap_no_data(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_ads: Project,
) -> None:
    """Test retrieving overlap when no data exists."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_ads.id}/ads/seo-overlap",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    # Should return empty data, not an error
    assert "data" in data
    assert "total" in data


# ==================== Test Authorization ====================


def test_get_campaigns_unauthorized_user(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test that users can only access their own project's Ads data."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{other_project.id}/ads/campaigns",
        headers=normal_user_token_headers,
    )

    # Should return 403 or 400 for unauthorized access
    assert response.status_code in [403, 400]


def test_link_ads_account_unauthorized_user(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test that users cannot link Ads to another user's project."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{other_project.id}/ads/link",
        headers=normal_user_token_headers,
        json={"customer_id": "1234567890"},
    )

    # Should return 403 or 400 for unauthorized access
    assert response.status_code in [403, 400]


# ==================== Test 404 for missing project ====================


def test_get_campaigns_project_not_found(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    """Test retrieving campaigns for non-existent project returns 404."""
    fake_project_id = uuid.uuid4()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{fake_project_id}/ads/campaigns",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]


def test_link_ads_account_project_not_found(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    """Test linking ads account for non-existent project returns 404."""
    fake_project_id = uuid.uuid4()

    response = client.post(
        f"{settings.API_V1_STR}/projects/{fake_project_id}/ads/link",
        headers=normal_user_token_headers,
        json={"customer_id": "1234567890"},
    )

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]
