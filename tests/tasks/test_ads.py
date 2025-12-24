"""Tests for Ads Celery tasks."""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlmodel import Session

from app.core.celery import celery_app
from app.models.ads import AdsAccount, AdsCampaignDaily, AdsKeywordDaily
from app.models.integration import IntegrationAccount
from app.models.project import Project


class TestAdsTaskRegistration:
    """Test that Ads tasks are properly registered in the Celery app."""

    def test_sync_ads_account_task_exists(self) -> None:
        """Test that sync_ads_account task is registered."""
        assert "app.tasks.ads.sync_ads_account" in celery_app.tasks


class TestSyncAdsAccountTask:
    """Test sync_ads_account task."""

    @patch("app.tasks.ads.Session")
    @patch("app.tasks.ads.GoogleOAuthClient")
    @patch("app.tasks.ads.GoogleAdsService")
    def test_sync_ads_account_success(
        self,
        mock_ads_service_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test successful sync of Google Ads account."""
        from app.tasks.ads import sync_ads_account

        # Setup test data
        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database objects
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock AdsAccount
        mock_ads_account = Mock(spec=AdsAccount)
        mock_ads_account.id = uuid.uuid4()
        mock_ads_account.customer_id = "1234567890"
        mock_ads_account.sync_status = "pending"
        mock_ads_account.last_sync_at = None

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.ads_account = mock_ads_account

        # Mock integration account
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.id = uuid.uuid4()
        mock_account.access_token_encrypted = "encrypted_access"
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Track exec calls
        exec_calls = []

        def exec_side_effect(stmt: object) -> Mock:
            exec_calls.append(stmt)
            result_mock = Mock()
            # First call is for integration account
            if len(exec_calls) == 1:
                result_mock.first.return_value = mock_account
            else:
                # Subsequent calls are for delete queries
                result_mock.all.return_value = []
            return result_mock

        # Track deleted records
        deleted_items = []

        def delete_side_effect(item: object) -> None:
            deleted_items.append(item)

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project
        mock_session.delete.side_effect = delete_side_effect

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock Google Ads service
        mock_ads_service = Mock()

        # Mock campaign performance data
        today = date.today()
        mock_campaigns = [
            {
                "date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                "campaign_id": "111",
                "campaign_name": "Campaign 1",
                "campaign_status": "ENABLED",
                "impressions": 1000,
                "clicks": 50,
                "cost_micros": 5000000,
                "conversions": 2.0,
                "conversion_value": 100.0,
            },
            {
                "date": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                "campaign_id": "111",
                "campaign_name": "Campaign 1",
                "campaign_status": "ENABLED",
                "impressions": 800,
                "clicks": 40,
                "cost_micros": 4000000,
                "conversions": 1.5,
                "conversion_value": 75.0,
            },
        ]

        # Mock keyword performance data
        mock_keywords = [
            {
                "date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                "campaign_id": "111",
                "ad_group_id": "222",
                "criterion_id": "333",
                "keyword_text": "seo tools",
                "match_type": "EXACT",
                "quality_score": 8,
                "final_url": "https://example.com/landing",
                "impressions": 500,
                "clicks": 25,
                "cost_micros": 2500000,
                "conversions": 1.0,
                "average_cpc_micros": 100000,
            },
            {
                "date": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                "campaign_id": "111",
                "ad_group_id": "222",
                "criterion_id": "333",
                "keyword_text": "seo tools",
                "match_type": "EXACT",
                "quality_score": 8,
                "final_url": "https://example.com/landing",
                "impressions": 400,
                "clicks": 20,
                "cost_micros": 2000000,
                "conversions": 0.75,
                "average_cpc_micros": 100000,
            },
        ]

        mock_ads_service.get_campaign_performance.return_value = mock_campaigns
        mock_ads_service.get_keyword_performance.return_value = mock_keywords
        mock_ads_service_class.return_value = mock_ads_service

        # Execute task
        result = sync_ads_account(project_id)

        # Assertions
        assert result["campaigns_synced"] == 2
        assert result["keywords_synced"] == 2

        # Verify GoogleAdsService was created with correct params
        mock_ads_service_class.assert_called_once_with(
            refresh_token="decrypted_encrypted_refresh",
            customer_id="1234567890"
        )

        # Verify data retrieval methods were called
        mock_ads_service.get_campaign_performance.assert_called_once()
        mock_ads_service.get_keyword_performance.assert_called_once()

        # Verify ads account status was updated
        assert mock_ads_account.sync_status == "completed"
        assert mock_ads_account.last_sync_at is not None

    @patch("app.tasks.ads.Session")
    def test_sync_ads_account_missing_project(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing project gracefully."""
        from app.tasks.ads import sync_ads_account

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.get.return_value = None

        # Execute task
        result = sync_ads_account(str(uuid.uuid4()))

        # Assertions
        assert "error" in result
        assert "project not found" in result["error"].lower()

    @patch("app.tasks.ads.Session")
    def test_sync_ads_account_missing_ads_account(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing AdsAccount."""
        from app.tasks.ads import sync_ads_account

        project_id = str(uuid.uuid4())

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project exists but no ads_account
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.ads_account = None

        mock_session.get.return_value = mock_project

        # Execute task
        result = sync_ads_account(project_id)

        # Assertions
        assert "error" in result
        assert "ads account not found" in result["error"].lower()

    @patch("app.tasks.ads.Session")
    def test_sync_ads_account_missing_integration(self, mock_session_class: Mock) -> None:
        """Test sync task handles missing integration account."""
        from app.tasks.ads import sync_ads_account

        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock project with AdsAccount
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id

        mock_ads_account = Mock(spec=AdsAccount)
        mock_ads_account.customer_id = "1234567890"
        mock_project.ads_account = mock_ads_account

        # Configure session to return project but not integration
        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = None  # No integration account
            return result_mock

        mock_session.get.return_value = mock_project
        mock_session.exec.side_effect = exec_side_effect

        # Execute task
        result = sync_ads_account(project_id)

        # Assertions
        assert "error" in result
        assert "integration account not found" in result["error"].lower()

    @patch("app.tasks.ads.Session")
    @patch("app.tasks.ads.GoogleOAuthClient")
    @patch("app.tasks.ads.GoogleAdsService")
    def test_sync_ads_account_clears_existing_data(
        self,
        mock_ads_service_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test that sync clears existing data for date range before inserting new data."""
        from app.tasks.ads import sync_ads_account

        # Setup test data
        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database objects
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock AdsAccount
        mock_ads_account = Mock(spec=AdsAccount)
        mock_ads_account.customer_id = "1234567890"

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.ads_account = mock_ads_account

        # Mock integration account
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Track exec calls
        exec_calls = []

        def exec_side_effect(stmt: object) -> Mock:
            exec_calls.append(stmt)
            result_mock = Mock()
            # First call is for integration account, second onwards for deletes
            if len(exec_calls) == 1:
                result_mock.first.return_value = mock_account
            else:
                result_mock.all.return_value = []  # Mock existing data to delete
            return result_mock

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock Google Ads service with minimal data
        mock_ads_service = Mock()
        mock_ads_service.get_campaign_performance.return_value = []
        mock_ads_service.get_keyword_performance.return_value = []
        mock_ads_service_class.return_value = mock_ads_service

        # Execute task
        sync_ads_account(project_id)

        # Verify that exec was called multiple times (integration lookup + delete queries)
        assert len(exec_calls) >= 3  # At least: integration, campaign delete, keyword delete

    @patch("app.tasks.ads.Session")
    @patch("app.tasks.ads.GoogleOAuthClient")
    @patch("app.tasks.ads.GoogleAdsService")
    def test_sync_ads_account_updates_timestamp(
        self,
        mock_ads_service_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test that AdsAccount timestamps are updated after sync."""
        from app.tasks.ads import sync_ads_account

        # Setup test data
        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database objects
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock AdsAccount with initial values
        mock_ads_account = Mock(spec=AdsAccount)
        mock_ads_account.customer_id = "1234567890"
        mock_ads_account.last_sync_at = None
        mock_ads_account.sync_status = "pending"

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.ads_account = mock_ads_account

        # Mock integration account
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = mock_account
            result_mock.all.return_value = []
            return result_mock

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock Google Ads service
        mock_ads_service = Mock()
        mock_ads_service.get_campaign_performance.return_value = []
        mock_ads_service.get_keyword_performance.return_value = []
        mock_ads_service_class.return_value = mock_ads_service

        # Execute task
        sync_ads_account(project_id)

        # Verify timestamps were updated
        assert mock_ads_account.last_sync_at is not None
        assert mock_ads_account.sync_status == "completed"

        # Verify session.add was called with ads_account
        mock_session.add.assert_any_call(mock_ads_account)

    @patch("app.tasks.ads.Session")
    @patch("app.tasks.ads.GoogleOAuthClient")
    @patch("app.tasks.ads.GoogleAdsService")
    def test_sync_ads_account_error_handling(
        self,
        mock_ads_service_class: Mock,
        mock_oauth_class: Mock,
        mock_session_class: Mock,
    ) -> None:
        """Test that errors are properly handled and status updated."""
        from app.tasks.ads import sync_ads_account

        # Setup test data
        project_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        # Mock database objects
        mock_session = MagicMock(spec=Session)
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Mock AdsAccount
        mock_ads_account = Mock(spec=AdsAccount)
        mock_ads_account.customer_id = "1234567890"
        mock_ads_account.sync_status = "pending"

        # Mock project
        mock_project = Mock(spec=Project)
        mock_project.id = uuid.UUID(project_id)
        mock_project.created_by_id = user_id
        mock_project.ads_account = mock_ads_account

        # Mock integration account
        mock_account = Mock(spec=IntegrationAccount)
        mock_account.refresh_token_encrypted = "encrypted_refresh"
        mock_account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        def exec_side_effect(stmt: object) -> Mock:
            result_mock = Mock()
            result_mock.first.return_value = mock_account
            result_mock.all.return_value = []
            return result_mock

        mock_session.exec.side_effect = exec_side_effect
        mock_session.get.return_value = mock_project

        # Mock OAuth client
        mock_oauth = Mock()
        mock_oauth.decrypt_token.side_effect = lambda x: f"decrypted_{x}"
        mock_oauth_class.return_value = mock_oauth

        # Mock Google Ads service to raise an exception
        mock_ads_service = Mock()
        mock_ads_service.get_campaign_performance.side_effect = Exception("API Error")
        mock_ads_service_class.return_value = mock_ads_service

        # Execute task
        result = sync_ads_account(project_id)

        # Verify error is returned
        assert "error" in result
        assert "api error" in result["error"].lower()

        # Verify sync_status was updated to error
        assert mock_ads_account.sync_status == "error"
