"""Tests for Google Ads API client service."""
import pytest
from datetime import date
from unittest.mock import Mock, MagicMock, patch
from google.ads.googleads.errors import GoogleAdsException
from google.api_core.exceptions import GoogleAPIError


class TestGoogleAdsService:
    """Test suite for GoogleAdsService class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for Google Ads API configuration."""
        mock = Mock()
        mock.GOOGLE_ADS_DEVELOPER_TOKEN = "test-developer-token"
        mock.GOOGLE_CLIENT_ID = "test-client-id"
        mock.GOOGLE_CLIENT_SECRET = "test-client-secret"
        return mock

    @pytest.fixture
    def google_ads_service(self, mock_settings):
        """Create a GoogleAdsService instance with mocked dependencies."""
        with patch("app.services.ads.google_ads.settings", mock_settings):
            with patch("app.services.ads.google_ads.GoogleAdsClient") as mock_client_class:
                # Mock the GoogleAdsClient initialization
                mock_client = MagicMock()
                mock_client_class.return_value = mock_client

                from app.services.ads.google_ads import GoogleAdsService

                service = GoogleAdsService(
                    refresh_token="test-refresh-token",
                    customer_id="1234567890"
                )
                service.client = mock_client
                return service

    def test_init_creates_client_with_credentials(self, mock_settings):
        """Test that initialization creates GoogleAdsClient with proper credentials."""
        with patch("app.services.ads.google_ads.settings", mock_settings):
            with patch("app.services.ads.google_ads.GoogleAdsClient") as mock_client_class:
                with patch("app.services.ads.google_ads.google_oauth2_credentials") as mock_creds_module:
                    mock_credentials = MagicMock()
                    mock_creds_module.Credentials.return_value = mock_credentials

                    from app.services.ads.google_ads import GoogleAdsService

                    service = GoogleAdsService(
                        refresh_token="test-refresh-token",
                        customer_id="1234567890"
                    )

                    # Verify credentials were created with correct parameters
                    mock_creds_module.Credentials.assert_called_once_with(
                        None,
                        refresh_token="test-refresh-token",
                        client_id="test-client-id",
                        client_secret="test-client-secret",
                        token_uri="https://accounts.google.com/o/oauth2/token"
                    )

                    # Verify GoogleAdsClient was created
                    mock_client_class.assert_called_once_with(
                        mock_credentials,
                        "test-developer-token"
                    )

                    # Verify customer_id was stored
                    assert service.customer_id == "1234567890"

    def test_list_accessible_customers_success(self, google_ads_service):
        """Test list_accessible_customers returns list of customer dictionaries."""
        # Mock CustomerService
        mock_customer_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_customer_service

        # Mock list_accessible_customers response
        mock_response = MagicMock()
        mock_response.resource_names = [
            "customers/1234567890",
            "customers/9876543210"
        ]
        mock_customer_service.list_accessible_customers.return_value = mock_response

        # Mock _get_customer_details to return customer info
        with patch.object(google_ads_service, "_get_customer_details") as mock_get_details:
            mock_get_details.side_effect = [
                {
                    "customer_id": "1234567890",
                    "name": "Test Customer 1",
                    "currency": "USD",
                    "timezone": "America/New_York"
                },
                {
                    "customer_id": "9876543210",
                    "name": "Test Customer 2",
                    "currency": "EUR",
                    "timezone": "Europe/London"
                }
            ]

            result = google_ads_service.list_accessible_customers()

            # Verify CustomerService was called
            google_ads_service.client.get_service.assert_called_once_with("CustomerService")
            mock_customer_service.list_accessible_customers.assert_called_once()

            # Verify result structure
            assert len(result) == 2
            assert result[0]["customer_id"] == "1234567890"
            assert result[0]["name"] == "Test Customer 1"
            assert result[0]["currency"] == "USD"
            assert result[0]["timezone"] == "America/New_York"
            assert result[1]["customer_id"] == "9876543210"
            assert result[1]["name"] == "Test Customer 2"

    def test_list_accessible_customers_empty(self, google_ads_service):
        """Test list_accessible_customers handles empty response."""
        mock_customer_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_customer_service

        mock_response = MagicMock()
        mock_response.resource_names = []
        mock_customer_service.list_accessible_customers.return_value = mock_response

        result = google_ads_service.list_accessible_customers()

        assert result == []

    def test_get_customer_details_success(self, google_ads_service):
        """Test _get_customer_details returns customer information."""
        # Mock GoogleAdsService
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Mock search_stream response
        mock_row = MagicMock()
        mock_row.customer.id = 1234567890
        mock_row.customer.descriptive_name = "Test Customer"
        mock_row.customer.currency_code = "USD"
        mock_row.customer.time_zone = "America/New_York"

        mock_ga_service.search_stream.return_value = [[mock_row]]

        result = google_ads_service._get_customer_details("1234567890")

        # Verify query was executed
        expected_query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone
            FROM customer
            LIMIT 1
        """
        google_ads_service.client.get_service.assert_called_with("GoogleAdsService")
        mock_ga_service.search_stream.assert_called_once()

        # Verify result structure
        assert result["customer_id"] == "1234567890"
        assert result["name"] == "Test Customer"
        assert result["currency"] == "USD"
        assert result["timezone"] == "America/New_York"

    def test_get_customer_details_not_found(self, google_ads_service):
        """Test _get_customer_details returns None when customer not found."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Empty response
        mock_ga_service.search_stream.return_value = []

        result = google_ads_service._get_customer_details("1234567890")

        assert result is None

    def test_get_campaign_performance_success(self, google_ads_service):
        """Test get_campaign_performance returns campaign data with metrics."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Mock campaign performance data
        mock_row1 = MagicMock()
        mock_row1.segments.date = "2025-01-01"
        mock_row1.campaign.id = 111
        mock_row1.campaign.name = "Campaign 1"
        mock_row1.campaign.status.name = "ENABLED"
        mock_row1.metrics.impressions = 1000
        mock_row1.metrics.clicks = 50
        mock_row1.metrics.cost_micros = 25000000  # $25.00
        mock_row1.metrics.conversions = 5.0
        mock_row1.metrics.conversions_value = 250.0

        mock_row2 = MagicMock()
        mock_row2.segments.date = "2025-01-02"
        mock_row2.campaign.id = 222
        mock_row2.campaign.name = "Campaign 2"
        mock_row2.campaign.status.name = "PAUSED"
        mock_row2.metrics.impressions = 500
        mock_row2.metrics.clicks = 25
        mock_row2.metrics.cost_micros = 12500000  # $12.50
        mock_row2.metrics.conversions = 2.0
        mock_row2.metrics.conversions_value = 100.0

        mock_ga_service.search_stream.return_value = [[mock_row1, mock_row2]]

        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 2)

        result = google_ads_service.get_campaign_performance(start_date, end_date)

        # Verify query was executed with date range
        google_ads_service.client.get_service.assert_called_with("GoogleAdsService")
        call_args = mock_ga_service.search_stream.call_args
        query = call_args[1]["query"]

        # Verify date range in query
        assert "segments.date BETWEEN '2025-01-01' AND '2025-01-02'" in query
        assert "FROM campaign" in query
        assert "campaign.id" in query
        assert "metrics.impressions" in query

        # Verify result structure
        assert len(result) == 2
        assert result[0]["date"] == "2025-01-01"
        assert result[0]["campaign_id"] == 111
        assert result[0]["campaign_name"] == "Campaign 1"
        assert result[0]["campaign_status"] == "ENABLED"
        assert result[0]["impressions"] == 1000
        assert result[0]["clicks"] == 50
        assert result[0]["cost_micros"] == 25000000
        assert result[0]["conversions"] == 5.0
        assert result[0]["conversion_value"] == 250.0

        assert result[1]["date"] == "2025-01-02"
        assert result[1]["campaign_id"] == 222

    def test_get_campaign_performance_empty(self, google_ads_service):
        """Test get_campaign_performance handles empty response."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service
        mock_ga_service.search_stream.return_value = []

        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 2)

        result = google_ads_service.get_campaign_performance(start_date, end_date)

        assert result == []

    def test_get_keyword_performance_success(self, google_ads_service):
        """Test get_keyword_performance returns keyword-level data with metrics."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Mock keyword performance data
        mock_row1 = MagicMock()
        mock_row1.segments.date = "2025-01-01"
        mock_row1.campaign.id = 111
        mock_row1.ad_group.id = 222
        mock_row1.ad_group_criterion.criterion_id = 333
        mock_row1.ad_group_criterion.keyword.text = "python tutorial"
        mock_row1.ad_group_criterion.keyword.match_type.name = "EXACT"
        mock_row1.ad_group_criterion.quality_info.quality_score = 8
        mock_row1.ad_group_criterion.final_urls = ["https://example.com/python"]
        mock_row1.metrics.impressions = 100
        mock_row1.metrics.clicks = 10
        mock_row1.metrics.cost_micros = 5000000  # $5.00
        mock_row1.metrics.conversions = 1.0
        mock_row1.metrics.average_cpc = 500000  # $0.50

        mock_row2 = MagicMock()
        mock_row2.segments.date = "2025-01-02"
        mock_row2.campaign.id = 111
        mock_row2.ad_group.id = 333
        mock_row2.ad_group_criterion.criterion_id = 444
        mock_row2.ad_group_criterion.keyword.text = "learn python"
        mock_row2.ad_group_criterion.keyword.match_type.name = "PHRASE"
        mock_row2.ad_group_criterion.quality_info.quality_score = 7
        mock_row2.ad_group_criterion.final_urls = ["https://example.com/learn"]
        mock_row2.metrics.impressions = 200
        mock_row2.metrics.clicks = 15
        mock_row2.metrics.cost_micros = 7500000  # $7.50
        mock_row2.metrics.conversions = 2.0
        mock_row2.metrics.average_cpc = 500000  # $0.50

        mock_ga_service.search_stream.return_value = [[mock_row1, mock_row2]]

        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 2)

        result = google_ads_service.get_keyword_performance(start_date, end_date)

        # Verify query was executed with date range
        google_ads_service.client.get_service.assert_called_with("GoogleAdsService")
        call_args = mock_ga_service.search_stream.call_args
        query = call_args[1]["query"]

        # Verify query contains keyword_view fields
        assert "segments.date BETWEEN '2025-01-01' AND '2025-01-02'" in query
        assert "FROM keyword_view" in query
        assert "ad_group_criterion.keyword.text" in query

        # Verify result structure
        assert len(result) == 2
        assert result[0]["date"] == "2025-01-01"
        assert result[0]["campaign_id"] == 111
        assert result[0]["ad_group_id"] == 222
        assert result[0]["criterion_id"] == 333
        assert result[0]["keyword_text"] == "python tutorial"
        assert result[0]["match_type"] == "EXACT"
        assert result[0]["quality_score"] == 8
        assert result[0]["final_url"] == "https://example.com/python"
        assert result[0]["impressions"] == 100
        assert result[0]["clicks"] == 10
        assert result[0]["cost_micros"] == 5000000
        assert result[0]["conversions"] == 1.0
        assert result[0]["average_cpc_micros"] == 500000

        assert result[1]["date"] == "2025-01-02"
        assert result[1]["keyword_text"] == "learn python"

    def test_get_keyword_performance_empty(self, google_ads_service):
        """Test get_keyword_performance handles empty response."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service
        mock_ga_service.search_stream.return_value = []

        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 2)

        result = google_ads_service.get_keyword_performance(start_date, end_date)

        assert result == []

    def test_google_ads_exception_handling(self, google_ads_service):
        """Test proper handling of GoogleAdsException."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Create a mock exception with required parameters
        exception = GoogleAdsException(
            error=MagicMock(),
            call=None,
            failure=MagicMock(),
            request_id="test-request-id"
        )

        mock_ga_service.search_stream.side_effect = exception

        # Verify exception is raised
        with pytest.raises(GoogleAdsException):
            google_ads_service.get_campaign_performance(
                date(2025, 1, 1),
                date(2025, 1, 2)
            )

    def test_date_range_formatting(self, google_ads_service):
        """Test date range is correctly formatted in GAQL queries."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service
        mock_ga_service.search_stream.return_value = []

        start_date = date(2025, 12, 1)
        end_date = date(2025, 12, 31)

        google_ads_service.get_campaign_performance(start_date, end_date)

        # Extract query from call
        call_args = mock_ga_service.search_stream.call_args
        query = call_args[1]["query"]

        # Verify date format YYYY-MM-DD
        assert "2025-12-01" in query
        assert "2025-12-31" in query
        assert "BETWEEN '2025-12-01' AND '2025-12-31'" in query

    def test_keyword_performance_with_missing_final_url(self, google_ads_service):
        """Test keyword performance handles missing final_urls gracefully."""
        mock_ga_service = MagicMock()
        google_ads_service.client.get_service.return_value = mock_ga_service

        # Mock row with empty final_urls
        mock_row = MagicMock()
        mock_row.segments.date = "2025-01-01"
        mock_row.campaign.id = 111
        mock_row.ad_group.id = 222
        mock_row.ad_group_criterion.criterion_id = 333
        mock_row.ad_group_criterion.keyword.text = "test keyword"
        mock_row.ad_group_criterion.keyword.match_type.name = "BROAD"
        mock_row.ad_group_criterion.quality_info.quality_score = 5
        mock_row.ad_group_criterion.final_urls = []  # Empty list
        mock_row.metrics.impressions = 50
        mock_row.metrics.clicks = 5
        mock_row.metrics.cost_micros = 2500000
        mock_row.metrics.conversions = 0.5
        mock_row.metrics.average_cpc = 500000

        mock_ga_service.search_stream.return_value = [[mock_row]]

        result = google_ads_service.get_keyword_performance(
            date(2025, 1, 1),
            date(2025, 1, 2)
        )

        # Should use empty string or None when final_urls is empty
        assert len(result) == 1
        assert result[0]["final_url"] in ["", None]
