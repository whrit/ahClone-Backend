"""Google Ads API client wrapper service."""
from datetime import date
from google.ads.googleads.client import GoogleAdsClient
from google.oauth2 import credentials as google_oauth2_credentials
from google.ads.googleads.errors import GoogleAdsException
from app.core.config import settings


class GoogleAdsService:
    """Google Ads API client wrapper for campaign and keyword performance data."""

    def __init__(self, refresh_token: str, customer_id: str):
        """
        Initialize Google Ads API client.

        Args:
            refresh_token: OAuth2 refresh token for the user
            customer_id: Google Ads customer ID (without dashes)
        """
        self.customer_id = customer_id

        # Create OAuth2 credentials
        credentials = google_oauth2_credentials.Credentials(
            None,
            refresh_token=refresh_token,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            token_uri="https://accounts.google.com/o/oauth2/token"
        )

        # Initialize GoogleAdsClient
        self.client = GoogleAdsClient(
            credentials,
            settings.GOOGLE_ADS_DEVELOPER_TOKEN
        )

    def list_accessible_customers(self) -> list[dict]:
        """
        List all customer accounts the user has access to.

        Returns:
            List of dictionaries with customer information:
            - customer_id: Customer ID (numeric string)
            - name: Descriptive name
            - currency: Currency code
            - timezone: Timezone string
        """
        customer_service = self.client.get_service("CustomerService")

        # Get accessible customer resource names
        response = customer_service.list_accessible_customers()

        customers = []
        for resource_name in response.resource_names:
            # Extract customer ID from resource name (format: "customers/1234567890")
            customer_id = resource_name.split("/")[-1]

            # Get detailed customer information
            customer_details = self._get_customer_details(customer_id)
            if customer_details:
                customers.append(customer_details)

        return customers

    def _get_customer_details(self, customer_id: str) -> dict | None:
        """
        Get details for a specific customer.

        Args:
            customer_id: Google Ads customer ID

        Returns:
            Dictionary with customer details or None if not found
        """
        ga_service = self.client.get_service("GoogleAdsService")

        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone
            FROM customer
            LIMIT 1
        """

        try:
            response = ga_service.search_stream(customer_id=customer_id, query=query)

            for batch in response:
                # Handle both mock list and actual GoogleAdsRow objects
                rows = batch if isinstance(batch, list) else batch.results
                for row in rows:
                    return {
                        "customer_id": str(row.customer.id),
                        "name": row.customer.descriptive_name,
                        "currency": row.customer.currency_code,
                        "timezone": row.customer.time_zone
                    }

            return None

        except GoogleAdsException:
            # If we can't access customer details, return None
            return None

    def get_campaign_performance(
        self,
        start_date: date,
        end_date: date
    ) -> list[dict]:
        """
        Get campaign performance data for a date range.

        Args:
            start_date: Start date for the report
            end_date: End date for the report

        Returns:
            List of dictionaries with campaign performance data:
            - date: Date string (YYYY-MM-DD)
            - campaign_id: Campaign ID
            - campaign_name: Campaign name
            - campaign_status: Campaign status (ENABLED, PAUSED, etc.)
            - impressions: Number of impressions
            - clicks: Number of clicks
            - cost_micros: Cost in micros (divide by 1,000,000 for currency value)
            - conversions: Number of conversions
            - conversion_value: Total conversion value
        """
        ga_service = self.client.get_service("GoogleAdsService")

        # Format dates as YYYY-MM-DD
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        query = f"""
            SELECT
                segments.date,
                campaign.id,
                campaign.name,
                campaign.status,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{start_str}' AND '{end_str}'
            ORDER BY segments.date, campaign.id
        """

        results = []
        response = ga_service.search_stream(customer_id=self.customer_id, query=query)

        for batch in response:
            # Handle both mock list and actual GoogleAdsRow objects
            rows = batch if isinstance(batch, list) else batch.results
            for row in rows:
                results.append({
                    "date": row.segments.date,
                    "campaign_id": row.campaign.id,
                    "campaign_name": row.campaign.name,
                    "campaign_status": row.campaign.status.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost_micros": row.metrics.cost_micros,
                    "conversions": row.metrics.conversions,
                    "conversion_value": row.metrics.conversions_value
                })

        return results

    def get_keyword_performance(
        self,
        start_date: date,
        end_date: date
    ) -> list[dict]:
        """
        Get keyword-level performance data for a date range.

        Args:
            start_date: Start date for the report
            end_date: End date for the report

        Returns:
            List of dictionaries with keyword performance data:
            - date: Date string (YYYY-MM-DD)
            - campaign_id: Campaign ID
            - ad_group_id: Ad group ID
            - criterion_id: Criterion (keyword) ID
            - keyword_text: Keyword text
            - match_type: Match type (EXACT, PHRASE, BROAD)
            - quality_score: Quality score (1-10)
            - final_url: Final URL
            - impressions: Number of impressions
            - clicks: Number of clicks
            - cost_micros: Cost in micros
            - conversions: Number of conversions
            - average_cpc_micros: Average CPC in micros
        """
        ga_service = self.client.get_service("GoogleAdsService")

        # Format dates as YYYY-MM-DD
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        query = f"""
            SELECT
                segments.date,
                campaign.id,
                ad_group.id,
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.final_urls,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.average_cpc
            FROM keyword_view
            WHERE segments.date BETWEEN '{start_str}' AND '{end_str}'
            ORDER BY segments.date, campaign.id, ad_group.id
        """

        results = []
        response = ga_service.search_stream(customer_id=self.customer_id, query=query)

        for batch in response:
            # Handle both mock list and actual GoogleAdsRow objects
            rows = batch if isinstance(batch, list) else batch.results
            for row in rows:
                # Get first final URL or empty string if not available
                final_url = ""
                if row.ad_group_criterion.final_urls:
                    final_url = row.ad_group_criterion.final_urls[0]

                results.append({
                    "date": row.segments.date,
                    "campaign_id": row.campaign.id,
                    "ad_group_id": row.ad_group.id,
                    "criterion_id": row.ad_group_criterion.criterion_id,
                    "keyword_text": row.ad_group_criterion.keyword.text,
                    "match_type": row.ad_group_criterion.keyword.match_type.name,
                    "quality_score": row.ad_group_criterion.quality_info.quality_score,
                    "final_url": final_url,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost_micros": row.metrics.cost_micros,
                    "conversions": row.metrics.conversions,
                    "average_cpc_micros": row.metrics.average_cpc
                })

        return results
