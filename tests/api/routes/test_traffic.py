"""Tests for Traffic API routes."""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Project, User
from app.models.ads import TrafficDaily
from app.models.gsc import GSCQueryDaily
from tests.utils.project import create_random_project
from tests.utils.user import create_random_user


class TestGetTrafficPanel:
    """Tests for GET /projects/{project_id}/traffic/panel endpoint."""

    def test_get_traffic_panel_success(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting traffic panel data successfully."""
        # Create project owned by normal user
        project = create_random_project(db, owner_id=normal_user.id)

        # Create sample TrafficDaily data (GA4)
        today = date.today()
        for i in range(5):
            traffic = TrafficDaily(
                project_id=project.id,
                date=today - timedelta(days=i),
                source_key="ga4",
                sessions=100 + i * 10,
                users=80 + i * 5,
                pageviews=200 + i * 20,
            )
            db.add(traffic)

        # Create sample GSCQueryDaily data
        for i in range(5):
            gsc_query = GSCQueryDaily(
                project_id=project.id,
                date=today - timedelta(days=i),
                query=f"test query {i}",
                clicks=50 + i * 5,
                impressions=500 + i * 50,
                ctr=0.1,
                position=10.0,
            )
            db.add(gsc_query)

        # Create sample CrUX data
        for i in range(5):
            crux = TrafficDaily(
                project_id=project.id,
                date=today - timedelta(days=i),
                source_key="crux",
                lcp_p75=2500.0 - i * 100,
                fid_p75=100.0 - i * 5,
                cls_p75=0.1 + i * 0.01,
            )
            db.add(crux)

        db.commit()

        # Make request
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/panel",
            headers=normal_user_token_headers,
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "total" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 28  # Default period_days

        # Check first data point
        first_row = data["data"][0]
        assert "date" in first_row
        assert "sessions" in first_row
        assert "users" in first_row
        assert "pageviews" in first_row
        assert "organic_clicks" in first_row
        assert "paid_clicks" in first_row

    def test_get_traffic_panel_with_period_days(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting traffic panel with custom period_days."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        # Request with period_days=7
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/panel?period_days=7",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 7

    def test_get_traffic_panel_project_not_found(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
    ) -> None:
        """Test getting traffic panel for non-existent project."""
        fake_project_id = uuid.uuid4()
        response = client.get(
            f"{settings.API_V1_STR}/projects/{fake_project_id}/traffic/panel",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_traffic_panel_unauthorized(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Test getting traffic panel for project owned by another user."""
        # Create project owned by a different user
        other_user = create_random_user(db)
        project = create_random_project(db, owner_id=other_user.id)
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/panel",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 400
        assert "not enough permissions" in response.json()["detail"].lower()

    def test_get_traffic_panel_no_auth(
        self,
        client: TestClient,
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting traffic panel without authentication."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/panel",
        )

        assert response.status_code == 401


class TestImportCSV:
    """Tests for POST /projects/{project_id}/traffic/import-csv endpoint."""

    def test_import_csv_success(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test importing CSV data successfully."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        # Prepare CSV data
        csv_data = [
            {
                "date": "2024-01-01",
                "sessions": "100",
                "users": "80",
                "pageviews": "200",
                "bounce_rate": "0.5",
                "avg_session_duration": "120.5",
            },
            {
                "date": "2024-01-02",
                "sessions": "110",
                "users": "85",
                "pageviews": "220",
                "bounce_rate": "0.45",
                "avg_session_duration": "130.0",
            },
        ]

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/import-csv",
            headers=normal_user_token_headers,
            json={"csv_data": csv_data},
        )

        assert response.status_code == 200
        data = response.json()
        assert "imported" in data
        assert data["imported"] == 2

    def test_import_csv_with_invalid_rows(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test importing CSV data with some invalid rows."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        # Mix of valid and invalid rows
        csv_data = [
            {
                "date": "2024-01-01",
                "sessions": "100",
                "users": "80",
            },
            {
                "date": "invalid-date",  # Invalid date
                "sessions": "110",
                "users": "85",
            },
            {
                "date": "2024-01-03",
                "sessions": "120",
                "users": "90",
            },
        ]

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/import-csv",
            headers=normal_user_token_headers,
            json={"csv_data": csv_data},
        )

        # Should succeed but only import valid rows
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 2  # Only 2 valid rows

    def test_import_csv_empty_data(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test importing empty CSV data."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/import-csv",
            headers=normal_user_token_headers,
            json={"csv_data": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 0

    def test_import_csv_project_not_found(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
    ) -> None:
        """Test importing CSV for non-existent project."""
        fake_project_id = uuid.uuid4()
        csv_data = [{"date": "2024-01-01", "sessions": "100"}]

        response = client.post(
            f"{settings.API_V1_STR}/projects/{fake_project_id}/traffic/import-csv",
            headers=normal_user_token_headers,
            json={"csv_data": csv_data},
        )

        assert response.status_code == 404

    def test_import_csv_unauthorized(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Test importing CSV for project owned by another user."""
        other_user = create_random_user(db)
        project = create_random_project(db, owner_id=other_user.id)
        db.commit()

        csv_data = [{"date": "2024-01-01", "sessions": "100"}]

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/import-csv",
            headers=normal_user_token_headers,
            json={"csv_data": csv_data},
        )

        assert response.status_code == 400

    def test_import_csv_no_auth(
        self,
        client: TestClient,
        db: Session,
        normal_user: User,
    ) -> None:
        """Test importing CSV without authentication."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        csv_data = [{"date": "2024-01-01", "sessions": "100"}]

        response = client.post(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/import-csv",
            json={"csv_data": csv_data},
        )

        assert response.status_code == 401


class TestGetAvailableSources:
    """Tests for GET /projects/{project_id}/traffic/sources endpoint."""

    def test_get_sources_success(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting available traffic sources successfully."""
        project = create_random_project(db, owner_id=normal_user.id)

        # Add traffic data from multiple sources
        today = date.today()
        for source in ["ga4", "gsc", "crux", "csv"]:
            if source == "gsc":
                # GSC data is from GSCQueryDaily
                gsc = GSCQueryDaily(
                    project_id=project.id,
                    date=today,
                    query="test",
                    clicks=10,
                    impressions=100,
                    ctr=0.1,
                    position=5.0,
                )
                db.add(gsc)
            else:
                traffic = TrafficDaily(
                    project_id=project.id,
                    date=today,
                    source_key=source,
                    sessions=100 if source == "ga4" else None,
                )
                db.add(traffic)

        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/sources",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert set(data) == {"ga4", "gsc", "crux", "csv"}

    def test_get_sources_no_data(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting sources when no data exists."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/sources",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_sources_project_not_found(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
    ) -> None:
        """Test getting sources for non-existent project."""
        fake_project_id = uuid.uuid4()
        response = client.get(
            f"{settings.API_V1_STR}/projects/{fake_project_id}/traffic/sources",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 404

    def test_get_sources_unauthorized(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Test getting sources for project owned by another user."""
        other_user = create_random_user(db)
        project = create_random_project(db, owner_id=other_user.id)
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/sources",
            headers=normal_user_token_headers,
        )

        assert response.status_code == 400

    def test_get_sources_no_auth(
        self,
        client: TestClient,
        db: Session,
        normal_user: User,
    ) -> None:
        """Test getting sources without authentication."""
        project = create_random_project(db, owner_id=normal_user.id)
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{project.id}/traffic/sources",
        )

        assert response.status_code == 401
