"""Tests for GSC API routes."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User
from app.models.gsc import (
    GSCPageDaily,
    GSCProperty,
    GSCQueryDaily,
    KeywordCluster,
    KeywordClusterMember,
)
from app.models.integration import IntegrationAccount
from app.models.project import Project
from tests.utils.project import create_random_project


@pytest.fixture
def project_with_gsc(db: Session, normal_user: User) -> Project:
    """Create a project with linked GSC property."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create GSC property for the project
    gsc_property = GSCProperty(
        project_id=project.id,
        site_url="sc-domain:example.com",
        permission_level="siteFullUser",
        verified=True,
        linked_at=datetime.now(timezone.utc),
        last_sync_at=datetime.now(timezone.utc) - timedelta(hours=1),
        sync_status="completed",
        search_type="web",
    )
    db.add(gsc_property)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def integration_account(db: Session, normal_user: User) -> IntegrationAccount:
    """Create an integration account for the user."""
    from app.core.oauth.google import GoogleOAuthClient

    oauth_client = GoogleOAuthClient()
    account = IntegrationAccount(
        user_id=normal_user.id,
        provider="google_gsc",
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
def gsc_query_data(db: Session, project_with_gsc: Project) -> list[GSCQueryDaily]:
    """Create sample GSC query data."""
    today = date.today()
    queries = []

    # Create queries with various patterns for opportunity detection
    query_configs = [
        # High impressions, low CTR (opportunity)
        {"query": "seo tools", "clicks": 50, "impressions": 5000, "ctr": 0.01, "position": 3.5},
        # Position 8-20 (quick win)
        {"query": "keyword research", "clicks": 20, "impressions": 500, "ctr": 0.04, "position": 12.0},
        # Normal performing query
        {"query": "content marketing", "clicks": 100, "impressions": 1000, "ctr": 0.10, "position": 5.0},
        # Low impressions (below threshold)
        {"query": "rare keyword", "clicks": 2, "impressions": 50, "ctr": 0.04, "position": 8.0},
    ]

    for config in query_configs:
        for days_ago in range(7):
            query_daily = GSCQueryDaily(
                project_id=project_with_gsc.id,
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


@pytest.fixture
def gsc_page_data(db: Session, project_with_gsc: Project) -> list[GSCPageDaily]:
    """Create sample GSC page data."""
    today = date.today()
    pages = []

    page_configs = [
        {"page": "https://example.com/blog", "clicks": 200, "impressions": 3000, "ctr": 0.067, "position": 8.5},
        {"page": "https://example.com/about", "clicks": 50, "impressions": 800, "ctr": 0.063, "position": 12.0},
    ]

    for config in page_configs:
        for days_ago in range(7):
            page_daily = GSCPageDaily(
                project_id=project_with_gsc.id,
                date=today - timedelta(days=days_ago),
                page=config["page"],
                country="USA",
                device="DESKTOP",
                clicks=config["clicks"],
                impressions=config["impressions"],
                ctr=config["ctr"],
                position=config["position"],
            )
            db.add(page_daily)
            pages.append(page_daily)

    db.commit()
    return pages


@pytest.fixture
def keyword_clusters(db: Session, project_with_gsc: Project) -> list[KeywordCluster]:
    """Create sample keyword clusters."""
    clusters = []

    cluster_configs = [
        {
            "label": "SEO Tools",
            "algorithm": "kmeans",
            "total_clicks": 500,
            "total_impressions": 10000,
            "avg_position": 5.5,
            "query_count": 15,
            "members": ["seo tools", "seo software", "seo platform"],
        },
        {
            "label": "Content Marketing",
            "algorithm": "kmeans",
            "total_clicks": 300,
            "total_impressions": 5000,
            "avg_position": 8.2,
            "query_count": 10,
            "members": ["content marketing", "content strategy", "content creation"],
        },
    ]

    for config in cluster_configs:
        cluster = KeywordCluster(
            project_id=project_with_gsc.id,
            label=config["label"],
            algorithm=config["algorithm"],
            total_clicks=config["total_clicks"],
            total_impressions=config["total_impressions"],
            avg_position=config["avg_position"],
            query_count=config["query_count"],
        )
        db.add(cluster)
        db.flush()

        # Add members
        for member_query in config["members"]:
            member = KeywordClusterMember(
                cluster_id=cluster.id,
                query=member_query,
                weight=0.8,
            )
            db.add(member)

        clusters.append(cluster)

    db.commit()
    return clusters


# ==================== Test list_available_properties ====================


def test_list_available_properties(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    integration_account: IntegrationAccount,
) -> None:
    """Test listing available GSC properties from Google API."""
    mock_sites = [
        {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"},
        {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
    ]

    with patch("app.api.routes.gsc.get_gsc_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.list_sites = AsyncMock(return_value=mock_sites)
        mock_get_client.return_value = mock_client

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/properties",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["siteUrl"] == "sc-domain:example.com"
        assert data[0]["permissionLevel"] == "siteFullUser"


def test_list_available_properties_no_integration(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test listing properties fails without integration account."""
    # Delete any existing integration accounts for this user
    stmt = select(IntegrationAccount).where(IntegrationAccount.user_id == normal_user.id)
    existing_accounts = db.exec(stmt).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    # Create a project without integration account
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/properties",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "Integration account not found" in response.json()["detail"]


def test_list_available_properties_unauthorized(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test listing properties for another user's project fails."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{other_project.id}/gsc/properties",
        headers=normal_user_token_headers,
    )

    assert response.status_code in [403, 400]


# ==================== Test link_property ====================


def test_link_property(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
    integration_account: IntegrationAccount,
) -> None:
    """Test linking a GSC property to a project."""
    # Create a project without GSC property
    project = create_random_project(db, owner_id=normal_user.id)

    mock_site_info = {
        "siteUrl": "sc-domain:example.com",
        "permissionLevel": "siteFullUser",
    }

    with patch("app.api.routes.gsc.get_gsc_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_site = AsyncMock(return_value=mock_site_info)
        mock_get_client.return_value = mock_client

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/gsc/link",
            headers=normal_user_token_headers,
            json={"site_url": "sc-domain:example.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["site_url"] == "sc-domain:example.com"
        assert data["permission_level"] == "siteFullUser"
        assert data["verified"] is True
        assert data["project_id"] == str(project.id)

        # Verify in database
        statement = select(GSCProperty).where(GSCProperty.project_id == project.id)
        gsc_property = db.exec(statement).first()
        assert gsc_property is not None
        assert gsc_property.site_url == "sc-domain:example.com"


def test_link_property_already_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    integration_account: IntegrationAccount,
) -> None:
    """Test linking a property that is already linked fails."""
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/link",
        headers=normal_user_token_headers,
        json={"site_url": "sc-domain:newsite.com"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "already" in detail and "linked" in detail


def test_link_property_no_integration(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test linking property fails without integration account."""
    # Delete any existing integration accounts for this user
    stmt = select(IntegrationAccount).where(IntegrationAccount.user_id == normal_user.id)
    existing_accounts = db.exec(stmt).all()
    for account in existing_accounts:
        db.delete(account)
    db.commit()

    project = create_random_project(db, owner_id=normal_user.id)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/link",
        headers=normal_user_token_headers,
        json={"site_url": "sc-domain:example.com"},
    )

    assert response.status_code == 404
    assert "Integration account not found" in response.json()["detail"]


# ==================== Test unlink_property ====================


def test_unlink_property(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    db: Session,
) -> None:
    """Test unlinking a GSC property from a project."""
    response = client.delete(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/unlink",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "GSC property unlinked successfully"

    # Verify in database
    statement = select(GSCProperty).where(GSCProperty.project_id == project_with_gsc.id)
    gsc_property = db.exec(statement).first()
    assert gsc_property is None


def test_unlink_property_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test unlinking a property that isn't linked fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.delete(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/unlink",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "GSC property not found" in response.json()["detail"]


# ==================== Test trigger_sync ====================


def test_trigger_sync(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test triggering a manual GSC sync."""
    with patch("app.api.routes.gsc.sync_gsc_property") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-123")

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/sync",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Sync task queued"
        assert data["task_id"] == "task-123"

        # Verify task was called with correct project_id
        mock_task.delay.assert_called_once_with(str(project_with_gsc.id))


def test_trigger_sync_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test triggering sync for project without GSC property fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/sync",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "GSC property not found" in response.json()["detail"]


# ==================== Test trigger_backfill ====================


def test_trigger_backfill(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test triggering a GSC data backfill."""
    with patch("app.api.routes.gsc.backfill_gsc_data") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-456")

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/backfill?days=90",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Backfill task queued"
        assert data["task_id"] == "task-456"
        assert data["days"] == 90

        # Verify task was called with correct parameters
        mock_task.delay.assert_called_once_with(str(project_with_gsc.id), 90)


def test_trigger_backfill_custom_days(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test triggering backfill with custom days parameter."""
    with patch("app.api.routes.gsc.backfill_gsc_data") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-789")

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/backfill?days=180",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 180

        mock_task.delay.assert_called_once_with(str(project_with_gsc.id), 180)


def test_trigger_backfill_exceeds_max_days(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test triggering backfill with days > 365 fails validation."""
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/backfill?days=400",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 422


# ==================== Test get_queries ====================


def test_get_queries(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving GSC query data."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/queries",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "count" in data
    assert isinstance(data["data"], list)
    assert data["count"] > 0

    # Verify data structure
    if len(data["data"]) > 0:
        first_query = data["data"][0]
        assert "query" in first_query
        assert "clicks" in first_query
        assert "impressions" in first_query
        assert "ctr" in first_query
        assert "position" in first_query


def test_get_queries_with_search_filter(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving queries with search filter."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/queries?search=seo",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data

    # All returned queries should contain "seo"
    for query_row in data["data"]:
        assert "seo" in query_row["query"].lower()


def test_get_queries_with_sorting(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving queries with custom sorting."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/queries?sort_by=impressions&sort_order=desc",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()

    # Verify sorting (impressions should be descending)
    impressions = [row["impressions"] for row in data["data"]]
    assert impressions == sorted(impressions, reverse=True)


def test_get_queries_with_pagination(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving queries with pagination."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/queries?skip=1&limit=2",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) <= 2


def test_get_queries_invalid_sort_field(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test retrieving queries with invalid sort field fails validation."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/queries?sort_by=invalid_field",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 422


# ==================== Test get_pages ====================


def test_get_pages(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_page_data: list[GSCPageDaily],
) -> None:
    """Test retrieving GSC page data."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/pages",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "count" in data
    assert isinstance(data["data"], list)
    assert data["count"] > 0

    # Verify data structure
    if len(data["data"]) > 0:
        first_page = data["data"][0]
        assert "page" in first_page
        assert "clicks" in first_page
        assert "impressions" in first_page
        assert "ctr" in first_page
        assert "position" in first_page


def test_get_pages_with_pagination(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_page_data: list[GSCPageDaily],
) -> None:
    """Test retrieving pages with pagination."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/pages?skip=0&limit=1",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) <= 1


# ==================== Test get_opportunities ====================


def test_get_opportunities(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving keyword opportunities."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/opportunities",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "count" in data
    assert isinstance(data["data"], list)

    # Verify data structure
    if len(data["data"]) > 0:
        first_opp = data["data"][0]
        assert "query" in first_opp
        assert "impressions" in first_opp
        assert "clicks" in first_opp
        assert "ctr" in first_opp
        assert "position" in first_opp
        assert "opportunity_type" in first_opp
        assert "potential_clicks" in first_opp


def test_get_opportunities_with_type_filter(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test retrieving opportunities filtered by type."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/opportunities?opportunity_type=low_ctr",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()

    # All returned opportunities should be of type "low_ctr"
    for opp in data["data"]:
        assert opp["opportunity_type"] == "low_ctr"


def test_get_opportunities_no_data(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test retrieving opportunities when no GSC data exists."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create GSC property but no data
    gsc_property = GSCProperty(
        project_id=project.id,
        site_url="sc-domain:example.com",
        permission_level="siteFullUser",
        verified=True,
        sync_status="completed",
    )
    db.add(gsc_property)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/opportunities",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert len(data["data"]) == 0


# ==================== Test get_clusters ====================


def test_get_clusters(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    keyword_clusters: list[KeywordCluster],
) -> None:
    """Test retrieving keyword clusters."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/clusters",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "count" in data
    assert isinstance(data["data"], list)
    assert data["count"] == 2

    # Verify data structure
    first_cluster = data["data"][0]
    assert "id" in first_cluster
    assert "label" in first_cluster
    assert "algorithm" in first_cluster
    assert "total_clicks" in first_cluster
    assert "total_impressions" in first_cluster
    assert "avg_position" in first_cluster
    assert "query_count" in first_cluster


def test_get_clusters_no_data(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test retrieving clusters when none exist."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/clusters",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert len(data["data"]) == 0


# ==================== Test generate_clusters ====================


def test_generate_clusters(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    gsc_query_data: list[GSCQueryDaily],
) -> None:
    """Test triggering cluster generation task."""
    with patch("app.api.routes.gsc.cluster_queries") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-cluster-123")

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/clusters/generate",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Cluster generation task queued"
        assert data["task_id"] == "task-cluster-123"

        # Verify task was called with correct project_id
        mock_task.delay.assert_called_once_with(str(project_with_gsc.id))


def test_generate_clusters_not_linked(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
) -> None:
    """Test generating clusters for project without GSC property fails."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/gsc/clusters/generate",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "GSC property not found" in response.json()["detail"]


# ==================== Test get_cluster_detail ====================


def test_get_cluster_detail(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
    keyword_clusters: list[KeywordCluster],
    gsc_query_data: list[GSCQueryDaily],
    db: Session,
) -> None:
    """Test retrieving detailed cluster information with members."""
    # Get the first cluster
    cluster = keyword_clusters[0]

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/clusters/{cluster.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()

    # Verify cluster-level fields
    assert data["id"] == str(cluster.id)
    assert data["project_id"] == str(project_with_gsc.id)
    assert data["label"] == cluster.label
    assert data["algorithm"] == cluster.algorithm
    assert "created_at" in data
    assert data["total_clicks"] == cluster.total_clicks
    assert data["total_impressions"] == cluster.total_impressions
    assert data["avg_position"] == cluster.avg_position
    assert data["query_count"] == cluster.query_count

    # Verify members array exists and has correct structure
    assert "members" in data
    assert isinstance(data["members"], list)
    assert len(data["members"]) > 0

    # Verify member fields including id and cluster_id
    first_member = data["members"][0]
    assert "id" in first_member
    assert "cluster_id" in first_member
    assert "query" in first_member
    assert "weight" in first_member
    assert "clicks" in first_member
    assert "impressions" in first_member
    assert "ctr" in first_member
    assert "position" in first_member

    # Verify member cluster_id matches cluster id
    assert first_member["cluster_id"] == str(cluster.id)


def test_get_cluster_detail_not_found(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    project_with_gsc: Project,
) -> None:
    """Test retrieving non-existent cluster returns 404."""
    fake_cluster_id = uuid.uuid4()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_with_gsc.id}/gsc/clusters/{fake_cluster_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "Cluster not found" in response.json()["detail"]


def test_get_cluster_detail_wrong_project(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    normal_user: User,
    keyword_clusters: list[KeywordCluster],
) -> None:
    """Test retrieving cluster from different project returns 404."""
    # Create a different project for the same user
    other_project = create_random_project(db, owner_id=normal_user.id)

    # Create GSC property for the other project
    gsc_property = GSCProperty(
        project_id=other_project.id,
        site_url="sc-domain:other.com",
        permission_level="siteFullUser",
        verified=True,
        sync_status="completed",
    )
    db.add(gsc_property)
    db.commit()

    # Try to get cluster from first project using second project's ID
    cluster = keyword_clusters[0]

    response = client.get(
        f"{settings.API_V1_STR}/projects/{other_project.id}/gsc/clusters/{cluster.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert "Cluster not found" in response.json()["detail"]


# ==================== Test Authorization ====================


def test_get_queries_unauthorized_user(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test that users can only access their own project's GSC data."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{other_project.id}/gsc/queries",
        headers=normal_user_token_headers,
    )

    # Should return 403 or 400 for unauthorized access
    assert response.status_code in [403, 400]


def test_link_property_unauthorized_user(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    """Test that users cannot link GSC to another user's project."""
    # Create a project for a different user
    other_project = create_random_project(db)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{other_project.id}/gsc/link",
        headers=normal_user_token_headers,
        json={"site_url": "sc-domain:example.com"},
    )

    # Should return 403 or 400 for unauthorized access
    assert response.status_code in [403, 400]
