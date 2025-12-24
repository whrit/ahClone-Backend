"""Tests for GSC Celery tasks."""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlmodel import Session

from app.core.celery import celery_app
from app.models.gsc import GSCProperty
from app.models.integration import IntegrationAccount
from app.models.project import Project


class TestGSCTaskRegistration:
    """Test that GSC tasks are properly registered in the Celery app."""

    def test_sync_gsc_property_task_exists(self) -> None:
        """Test that sync_gsc_property task is registered."""
        assert "app.tasks.gsc.sync_gsc_property" in celery_app.tasks

    def test_backfill_gsc_data_task_exists(self) -> None:
        """Test that backfill_gsc_data task is registered."""
        assert "app.tasks.gsc.backfill_gsc_data" in celery_app.tasks

    def test_compute_opportunities_task_exists(self) -> None:
        """Test that compute_opportunities task is registered."""
        assert "app.tasks.gsc.compute_opportunities" in celery_app.tasks

    def test_cluster_queries_task_exists(self) -> None:
        """Test that cluster_queries task is registered."""
        assert "app.tasks.gsc.cluster_queries" in celery_app.tasks


class TestSyncGSCPropertyTask:
    """Test sync_gsc_property task."""

    @patch("app.tasks.gsc.Session")
    @patch("app.tasks.gsc.GoogleOAuthClient")
    @patch("app.tasks.gsc.GSCClient")
    @patch("app.tasks.gsc.GSCIngestor")
    def test_sync_gsc_property_success(
        self,
        mock_ingestor_class: Mock,
        mock_client_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test successful sync of GSC property."""
        from app.tasks.gsc import sync_gsc_property

        # Setup test data
        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database objects
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock GSC property
        mock_gsc_property = Mock(spec=GSCProperty)
        mock_gsc_property.id = uuid.uuid4()
        mock_gsc_property.site_url = "sc-domain:example.com"
        mock_gsc_property.sync_status = "pending"

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.gsc_property = mock_gsc_property

        # Mock integration account with expired token
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.id = uuid.uuid4()
        mock_account.access_token_encrypted = "encrypted_access"
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # Configure session mock to return objects
        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = mock_account
            return result_mock

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth.refresh_token = AsyncMock(return_value={
            "access_token": "new_access",
            "expires_in": 3600,
        })
        mock_oauth.encrypt_token.side_effect = lambda x: f"encrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock GSC client
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock ingestor
        mock_ingestor = Mock()
        mock_ingestor.sync_queries = AsyncMock(return_value=100)
        mock_ingestor.sync_pages = AsyncMock(return_value=50)
        mock_ingestor_class.return_value = mock_ingestor

        # Execute task
        result = sync_gsc_property(project_id)

        # Assertions
        assert result["queries"] == 100
        assert result["pages"] == 50

        # Verify OAuth refresh was called
        mock_oauth.refresh_token.assert_called_once()

        # Verify ingestor methods were called
        mock_ingestor.sync_queries.assert_called_once()
        mock_ingestor.sync_pages.assert_called_once()

        # Verify property status was updated
        assert mock_gsc_property.sync_status == "completed"
        assert mock_gsc_property.last_sync_at is not None

    @patch("app.tasks.gsc.Session")
    def test_sync_gsc_property_missing_project(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing project gracefully."""
        from app.tasks.gsc import sync_gsc_property

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = None

        # Execute task
        result = sync_gsc_property(str(uuid.uuid4()))

        # Assertions
        assert "error" in result
        assert "not found" in result["error"].lower()

    @patch("app.tasks.gsc.Session")
    def test_sync_gsc_property_missing_gsc_property(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing GSC property."""
        from app.tasks.gsc import sync_gsc_property

        project_id = str(uuid.uuid4())

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project exists
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.gsc_property = None

        mock_session.get.return_value = mock_project

        # Execute task
        result = sync_gsc_property(project_id)

        # Assertions
        assert "error" in result
        assert "gsc property" in result["error"].lower()

    @patch("app.tasks.gsc.Session")
    def test_sync_gsc_property_missing_integration(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing integration account."""
        from app.tasks.gsc import sync_gsc_property

        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project with GSC property
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id

        mock_gsc_property = Mock(spec=GSCProperty)
        mock_project.gsc_property = mock_gsc_property

        # Configure session to return project but not integration
        def get_side_effect(model: type, id: uuid.UUID) -> Mock | None:
            if model == Project:
                return mock_project
            return None

        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = None  # No integration account
            return result_mock

        mock_session.get.side_effect = get_side_effect
        mock_session.exec.side_effect = exec_side_effect

        # Execute task
        result = sync_gsc_property(project_id)

        # Assertions
        assert "error" in result
        assert "integration" in result["error"].lower()


class TestBackfillGSCDataTask:
    """Test backfill_gsc_data task."""

    @patch("app.tasks.gsc.Session")
    @patch("app.tasks.gsc.GoogleOAuthClient")
    @patch("app.tasks.gsc.GSCClient")
    @patch("app.tasks.gsc.GSCIngestor")
    def test_backfill_gsc_data_success(
        self,
        mock_ingestor_class: Mock,
        mock_client_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test successful backfill of GSC data."""
        from app.tasks.gsc import backfill_gsc_data

        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock GSC property
        mock_gsc_property = Mock(spec=GSCProperty)
        mock_gsc_property.site_url = "sc-domain:example.com"

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.gsc_property = mock_gsc_property

        # Mock integration account (not expired)
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.access_token_encrypted = "encrypted_access"
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Configure session
        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = mock_account
            return result_mock

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock GSC client
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock ingestor with backfill
        mock_ingestor = Mock()
        mock_ingestor.backfill = AsyncMock(return_value={"queries": 5000, "pages": 1000})
        mock_ingestor_class.return_value = mock_ingestor

        # Execute task
        result = backfill_gsc_data(project_id, days=90)

        # Assertions
        assert result["queries"] == 5000
        assert result["pages"] == 1000

        # Verify backfill was called with correct days parameter
        mock_ingestor.backfill.assert_called_once()
        call_kwargs = mock_ingestor.backfill.call_args[1]
        assert call_kwargs["days"] == 90


class TestComputeOpportunitiesTask:
    """Test compute_opportunities task."""

    @patch("app.tasks.gsc.Session")
    @patch("app.tasks.gsc.OpportunityFinder")
    def test_compute_opportunities_success(
        self,
        mock_finder_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test successful computation of opportunities."""
        from app.tasks.gsc import compute_opportunities
        from app.services.gsc.opportunities import Opportunity, OpportunityType

        project_id = str(uuid.uuid4())

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_session.get.return_value = mock_project

        # Mock opportunity finder
        mock_finder = Mock()
        # Create mock opportunities
        mock_opportunities = [
            Opportunity(
                query="test query 1",
                page="http://example.com",
                clicks=10,
                impressions=1000,
                ctr=0.01,
                position=5.0,
                opportunity_type=OpportunityType.LOW_CTR,
                score=10.0,
            ),
            Opportunity(
                query="test query 2",
                page="http://example.com",
                clicks=5,
                impressions=500,
                ctr=0.01,
                position=10.0,
                opportunity_type=OpportunityType.POSITION_8_20,
                score=5.0,
            ),
        ]
        mock_finder.find_opportunities.return_value = iter(mock_opportunities)
        mock_finder_class.return_value = mock_finder

        # Execute task
        result = compute_opportunities(project_id)

        # Assertions
        assert result["total"] == 2
        assert result["by_type"]["low_ctr"] == 1
        assert result["by_type"]["position_8_20"] == 1

        # Verify finder was called
        mock_finder.find_opportunities.assert_called_once()

    @patch("app.tasks.gsc.Session")
    def test_compute_opportunities_missing_project(self, mock_session_class: Mock) -> None:
        """Test compute opportunities handles missing project."""
        from app.tasks.gsc import compute_opportunities

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = None

        # Execute task
        result = compute_opportunities(str(uuid.uuid4()))

        # Assertions
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestClusterQueriesTask:
    """Test cluster_queries task."""

    @patch("app.tasks.gsc.Session")
    @patch("app.tasks.gsc.QueryClusterer")
    def test_cluster_queries_success(
        self,
        mock_clusterer_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test successful query clustering."""
        from app.tasks.gsc import cluster_queries

        project_id = str(uuid.uuid4())

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_session.get.return_value = mock_project

        # Mock query clusterer
        mock_clusterer = Mock()
        mock_clusterer.cluster_queries.return_value = 12
        mock_clusterer_class.return_value = mock_clusterer

        # Execute task
        result = cluster_queries(project_id)

        # Assertions
        assert result["clusters_created"] == 12

        # Verify clusterer was called
        mock_clusterer.cluster_queries.assert_called_once()

    @patch("app.tasks.gsc.Session")
    def test_cluster_queries_missing_project(self, mock_session_class: Mock) -> None:
        """Test cluster queries handles missing project."""
        from app.tasks.gsc import cluster_queries

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = None

        # Execute task
        result = cluster_queries(str(uuid.uuid4()))

        # Assertions
        assert "error" in result
        assert "not found" in result["error"].lower()
