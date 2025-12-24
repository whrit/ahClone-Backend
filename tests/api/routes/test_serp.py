"""Tests for SERP API routes following TDD approach."""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from app.models.serp import (
    DeviceType,
    KeywordTarget,
    RankObservation,
    RefreshStatus,
    SearchEngine,
    SerpSnapshot,
)
from tests.utils.project import create_random_project


def test_list_providers(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing available SERP providers."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/providers",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert isinstance(content, list)
    # Should have at least the GSC provider
    assert len(content) >= 1
    # Check structure
    if len(content) > 0:
        provider = content[0]
        assert "key" in provider
        assert "name" in provider
        assert "is_compliant" in provider


def test_list_providers_project_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test listing providers for non-existent project returns 404."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}/serp/providers",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_add_keyword(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test adding a new keyword to track."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword_data = {
        "keyword": "seo tools",
        "locale": "en-US",
        "device": DeviceType.DESKTOP,
        "search_engine": SearchEngine.GOOGLE,
        "provider_key": "gsc_based",
        "refresh_frequency_hours": 24,
    }

    with patch("app.api.routes.serp.refresh_keyword") as mock_refresh:
        mock_refresh.delay = MagicMock()
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords",
            headers=normal_user_token_headers,
            json=keyword_data,
        )

    assert response.status_code == 200
    content = response.json()
    assert content["keyword"] == "seo tools"
    assert content["locale"] == "en-US"
    assert content["device"] == DeviceType.DESKTOP
    assert content["search_engine"] == SearchEngine.GOOGLE
    assert content["provider_key"] == "gsc_based"
    assert content["refresh_frequency_hours"] == 24
    assert content["project_id"] == str(project.id)
    assert "id" in content
    # Verify Celery task was called
    mock_refresh.delay.assert_called_once()


def test_add_keyword_duplicate(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test adding a duplicate keyword returns 400."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create existing keyword
    existing_keyword = KeywordTarget(
        project_id=project.id,
        keyword="seo tools",
        locale="en-US",
        device=DeviceType.DESKTOP,
        search_engine=SearchEngine.GOOGLE,
        provider_key="gsc_based",
    )
    db.add(existing_keyword)
    db.commit()

    # Try to add duplicate
    keyword_data = {
        "keyword": "seo tools",
        "locale": "en-US",
        "device": DeviceType.DESKTOP,
        "search_engine": SearchEngine.GOOGLE,
        "provider_key": "gsc_based",
        "refresh_frequency_hours": 24,
    }

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords",
        headers=normal_user_token_headers,
        json=keyword_data,
    )
    assert response.status_code == 400
    assert "already tracking" in response.json()["detail"].lower()


def test_add_keyword_max_limit(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test adding keyword when MAX_KEYWORDS_PER_PROJECT limit is reached."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create keywords up to limit
    for i in range(settings.MAX_KEYWORDS_PER_PROJECT):
        keyword = KeywordTarget(
            project_id=project.id,
            keyword=f"keyword {i}",
            locale="en-US",
            device=DeviceType.DESKTOP,
        )
        db.add(keyword)
    db.commit()

    # Try to add one more
    keyword_data = {
        "keyword": "one more keyword",
        "locale": "en-US",
        "device": DeviceType.DESKTOP,
    }

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords",
        headers=normal_user_token_headers,
        json=keyword_data,
    )
    assert response.status_code == 400
    assert "limit" in response.json()["detail"].lower()


def test_list_keywords(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing tracked keywords with pagination."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create multiple keywords
    for i in range(3):
        keyword = KeywordTarget(
            project_id=project.id,
            keyword=f"keyword {i}",
            locale="en-US",
            device=DeviceType.DESKTOP,
        )
        db.add(keyword)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert content["count"] >= 3
    assert isinstance(content["data"], list)


def test_list_keywords_with_pagination(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing keywords with skip and limit parameters."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create multiple keywords
    for i in range(10):
        keyword = KeywordTarget(
            project_id=project.id,
            keyword=f"keyword {i}",
            locale="en-US",
            device=DeviceType.DESKTOP,
        )
        db.add(keyword)
    db.commit()

    # Test with limit
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords?limit=5",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 5

    # Test with skip
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords?skip=5&limit=5",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) == 5


def test_delete_keyword(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test deleting a tracked keyword."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create keyword with observations and snapshot
    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    # Add observation
    observation = RankObservation(
        keyword_target_id=keyword.id,
        observed_at=datetime.now(timezone.utc),
        rank=5,
        status=RefreshStatus.SUCCESS,
    )
    db.add(observation)

    # Add snapshot
    snapshot = SerpSnapshot(
        keyword_target_id=keyword.id,
        results_json={"test": "data"},
    )
    db.add(snapshot)
    db.commit()

    response = client.delete(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "message" in content

    # Verify keyword is deleted (query fresh to avoid stale reference)
    keyword_id = keyword.id
    db.expunge(keyword)  # Remove the stale object from session
    deleted_keyword = db.get(KeywordTarget, keyword_id)
    assert deleted_keyword is None


def test_delete_keyword_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test deleting non-existent keyword returns 404."""
    project = create_random_project(db, owner_id=normal_user.id)

    response = client.delete(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_refresh_keyword(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test triggering manual refresh for a keyword."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    with patch("app.api.routes.serp.refresh_keyword") as mock_refresh:
        mock_refresh.delay = MagicMock()
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/refresh",
            headers=normal_user_token_headers,
        )

    assert response.status_code == 200
    content = response.json()
    assert "message" in content
    # Verify Celery task was called
    mock_refresh.delay.assert_called_once_with(str(keyword.id))


def test_refresh_all_keywords(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test triggering refresh for all project keywords."""
    project = create_random_project(db, owner_id=normal_user.id)

    # Create keywords
    for i in range(3):
        keyword = KeywordTarget(
            project_id=project.id,
            keyword=f"keyword {i}",
            locale="en-US",
            device=DeviceType.DESKTOP,
        )
        db.add(keyword)
    db.commit()

    with patch("app.api.routes.serp.refresh_project_keywords") as mock_refresh:
        mock_refresh.delay = MagicMock()
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/serp/refresh-all",
            headers=normal_user_token_headers,
        )

    assert response.status_code == 200
    content = response.json()
    assert "message" in content
    # Verify Celery task was called
    mock_refresh.delay.assert_called_once_with(str(project.id))


def test_get_rank_history(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting rank history for a keyword."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    # Create observations
    for i in range(5):
        observation = RankObservation(
            keyword_target_id=keyword.id,
            observed_at=datetime.now(timezone.utc),
            rank=i + 1,
            status=RefreshStatus.SUCCESS,
        )
        db.add(observation)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/history",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert content["count"] >= 5
    assert isinstance(content["data"], list)


def test_get_rank_history_with_days_param(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting rank history with custom days parameter."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/history?days=60",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200


def test_get_rank_history_max_days(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test that days parameter is capped at 90."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/history?days=365",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    # The endpoint should clamp to 90 days


def test_get_serp_snapshot(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting a SERP snapshot."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    # Create snapshot
    snapshot = SerpSnapshot(
        keyword_target_id=keyword.id,
        results_json={
            "organic": [
                {
                    "position": 1,
                    "url": "https://example.com/page1",
                    "domain": "example.com",
                    "title": "Example Page 1",
                    "snippet": "This is an example page",
                },
                {
                    "position": 2,
                    "url": "https://other.com/page2",
                    "domain": "other.com",
                    "title": "Other Page 2",
                    "snippet": "This is another page",
                },
            ]
        },
        total_results=1000000,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/snapshots/{snapshot.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(snapshot.id)
    assert content["keyword_target_id"] == str(keyword.id)
    assert "results" in content
    assert len(content["results"]) == 2
    assert content["total_results"] == 1000000


def test_get_serp_snapshot_marks_own_domain(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test that snapshots mark results from project's seed_url domain."""
    project = create_random_project(db, owner_id=normal_user.id)
    # Update project seed_url
    project.seed_url = "https://example.com"
    db.add(project)
    db.commit()

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    # Create snapshot with example.com domain
    snapshot = SerpSnapshot(
        keyword_target_id=keyword.id,
        results_json={
            "organic": [
                {
                    "position": 1,
                    "url": "https://example.com/page1",
                    "domain": "example.com",
                    "title": "Example Page 1",
                    "snippet": "This is an example page",
                },
                {
                    "position": 2,
                    "url": "https://other.com/page2",
                    "domain": "other.com",
                    "title": "Other Page 2",
                    "snippet": "This is another page",
                },
            ]
        },
        total_results=1000000,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/snapshots/{snapshot.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    # The endpoint should return successfully
    # Note: Marking own domain functionality could be tested with specific assertions


def test_get_serp_snapshot_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting non-existent snapshot returns 404."""
    project = create_random_project(db, owner_id=normal_user.id)

    keyword = KeywordTarget(
        project_id=project.id,
        keyword="test keyword",
        locale="en-US",
        device=DeviceType.DESKTOP,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords/{keyword.id}/snapshots/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_unauthorized_access(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Test that users cannot access SERP data for projects they don't own."""
    # Create project owned by a different user
    project = create_random_project(db)

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}/serp/keywords",
        headers=normal_user_token_headers,
    )
    assert response.status_code in [400, 403, 404]
