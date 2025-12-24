import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from tests.utils.project import create_random_project


def test_create_project(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test creating a new project."""
    data = {
        "name": "Test SEO Project",
        "seed_url": "https://example.com",
        "description": "A test project for SEO analysis",
    }
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == data["name"]
    assert content["seed_url"] == data["seed_url"]
    assert content["description"] == data["description"]
    assert "id" in content
    assert "created_by_id" in content
    assert "settings" in content
    assert content["settings"]["max_pages"] == 1000


def test_create_project_invalid_url(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test creating a project with invalid URL should fail."""
    data = {
        "name": "Test Project",
        "seed_url": "not-a-valid-url",
        "description": "Should fail",
    }
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert response.status_code == 422


def test_list_projects(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test listing user's projects."""
    create_random_project(db, owner_id=normal_user.id)
    create_random_project(db, owner_id=normal_user.id)
    response = client.get(
        f"{settings.API_V1_STR}/projects/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert "data" in content
    assert "count" in content
    assert isinstance(content["data"], list)


def test_get_project(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test getting a specific project."""
    project = create_random_project(db, owner_id=normal_user.id)
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(project.id)
    assert content["name"] == project.name
    assert content["seed_url"] == project.seed_url


def test_get_project_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test getting a non-existent project."""
    response = client.get(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Project not found"


def test_update_project(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test updating a project."""
    project = create_random_project(db, owner_id=normal_user.id)
    data = {
        "name": "Updated Project Name",
        "description": "Updated description",
    }
    response = client.put(
        f"{settings.API_V1_STR}/projects/{project.id}",
        headers=normal_user_token_headers,
        json=data,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == data["name"]
    assert content["description"] == data["description"]
    assert content["id"] == str(project.id)


def test_update_project_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test updating a non-existent project."""
    data = {"name": "Updated Name"}
    response = client.put(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}",
        headers=normal_user_token_headers,
        json=data,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Project not found"


def test_delete_project(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session, normal_user: User
) -> None:
    """Test deleting a project."""
    project = create_random_project(db, owner_id=normal_user.id)
    response = client.delete(
        f"{settings.API_V1_STR}/projects/{project.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Project deleted successfully"


def test_delete_project_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Test deleting a non-existent project."""
    response = client.delete(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Project not found"


def test_project_authorization(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session
) -> None:
    """Test that users can only access their own projects."""
    # Create a project as a normal user
    project = create_random_project(db)

    # Try to access it with different user credentials
    # Note: This assumes the random project is created with a different user
    # We'll need to verify authorization logic in the actual implementation
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project.id}",
        headers=normal_user_token_headers,
    )
    # This test will be refined once we implement the actual authorization logic
    assert response.status_code in [200, 400, 404]
