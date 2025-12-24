"""
Celery tasks for Google Ads workflow.

This module implements the Google Ads pipeline:
1. sync_ads_account: Daily sync of Google Ads data (campaigns and keywords)
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from sqlmodel import Session, select

from app.core.db import engine
from app.core.oauth.google import GoogleOAuthClient
from app.models.ads import AdsCampaignDaily, AdsKeywordDaily
from app.models.integration import IntegrationAccount
from app.models.project import Project
from app.services.ads.google_ads import GoogleAdsService


@shared_task(bind=True, name="app.tasks.ads.sync_ads_account")  # type: ignore[misc]
def sync_ads_account(self, project_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """
    Sync Google Ads data for a project.

    Steps:
    1. Get project and validate it exists
    2. Get AdsAccount linked to project
    3. Get IntegrationAccount for Google Ads (google_ads provider)
    4. Decrypt refresh token using GoogleOAuthClient
    5. Create GoogleAdsService with refresh_token and customer_id
    6. Sync last 7 days of data:
       - Delete existing AdsCampaignDaily and AdsKeywordDaily for date range
       - Get campaign performance from GoogleAdsService
       - Get keyword performance from GoogleAdsService
       - Create AdsCampaignDaily and AdsKeywordDaily records
    7. Update AdsAccount.last_sync_at and sync_status
    8. Return count of campaigns and keywords synced

    Args:
        project_id: UUID of the project

    Returns:
        Dictionary with sync results or error
    """
    try:
        with Session(engine) as session:
            # Step 1: Get project and validate it exists
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {"error": "Project not found"}

            # Step 2: Get AdsAccount linked to project
            ads_account = project.ads_account
            if not ads_account:
                return {"error": "Ads account not found"}

            # Step 3: Get IntegrationAccount for Google Ads (google_ads provider)
            stmt = select(IntegrationAccount).where(
                IntegrationAccount.user_id == project.created_by_id,
                IntegrationAccount.provider == "google_ads"
            )
            account = session.exec(stmt).first()
            if not account:
                return {"error": "Integration account not found"}

            # Step 4: Decrypt refresh token using GoogleOAuthClient
            oauth_client = GoogleOAuthClient()
            refresh_token = oauth_client.decrypt_token(account.refresh_token_encrypted)

            # Step 5: Create GoogleAdsService with refresh_token and customer_id
            ads_service = GoogleAdsService(
                refresh_token=refresh_token,
                customer_id=ads_account.customer_id
            )

            # Step 6: Sync last 7 days of data
            today = date.today()
            # Google Ads data typically has 1-2 day delay
            end_date = today - timedelta(days=2)
            start_date = end_date - timedelta(days=6)  # Last 7 days

            # Update ads_account status to syncing
            ads_account.sync_status = "syncing"
            session.add(ads_account)
            session.commit()

            # Delete existing AdsCampaignDaily for date range
            campaign_delete_stmt = select(AdsCampaignDaily).where(
                AdsCampaignDaily.project_id == project.id,
                AdsCampaignDaily.date >= start_date,
                AdsCampaignDaily.date <= end_date
            )
            existing_campaigns = session.exec(campaign_delete_stmt).all()
            for campaign in existing_campaigns:
                session.delete(campaign)

            # Delete existing AdsKeywordDaily for date range
            keyword_delete_stmt = select(AdsKeywordDaily).where(
                AdsKeywordDaily.project_id == project.id,
                AdsKeywordDaily.date >= start_date,
                AdsKeywordDaily.date <= end_date
            )
            existing_keywords = session.exec(keyword_delete_stmt).all()
            for keyword in existing_keywords:
                session.delete(keyword)

            session.commit()

            # Get campaign performance from GoogleAdsService
            campaigns_data = ads_service.get_campaign_performance(
                start_date=start_date,
                end_date=end_date
            )

            # Create AdsCampaignDaily records
            campaigns_count = 0
            for campaign in campaigns_data:
                # Parse date string to date object
                campaign_date = datetime.strptime(campaign["date"], "%Y-%m-%d").date()

                campaign_record = AdsCampaignDaily(
                    project_id=project.id,
                    date=campaign_date,
                    campaign_id=str(campaign["campaign_id"]),
                    campaign_name=campaign["campaign_name"],
                    campaign_status=campaign["campaign_status"],
                    impressions=campaign["impressions"],
                    clicks=campaign["clicks"],
                    cost_micros=campaign["cost_micros"],
                    conversions=campaign["conversions"],
                    conversion_value=campaign["conversion_value"]
                )
                session.add(campaign_record)
                campaigns_count += 1

            # Get keyword performance from GoogleAdsService
            keywords_data = ads_service.get_keyword_performance(
                start_date=start_date,
                end_date=end_date
            )

            # Create AdsKeywordDaily records
            keywords_count = 0
            for keyword in keywords_data:
                # Parse date string to date object
                keyword_date = datetime.strptime(keyword["date"], "%Y-%m-%d").date()

                keyword_record = AdsKeywordDaily(
                    project_id=project.id,
                    date=keyword_date,
                    campaign_id=str(keyword["campaign_id"]),
                    ad_group_id=str(keyword["ad_group_id"]),
                    criterion_id=str(keyword["criterion_id"]),
                    keyword_text=keyword["keyword_text"],
                    match_type=keyword["match_type"],
                    impressions=keyword["impressions"],
                    clicks=keyword["clicks"],
                    cost_micros=keyword["cost_micros"],
                    conversions=keyword["conversions"],
                    average_cpc_micros=keyword["average_cpc_micros"],
                    quality_score=keyword.get("quality_score"),
                    final_url=keyword.get("final_url")
                )
                session.add(keyword_record)
                keywords_count += 1

            # Commit all new records
            session.commit()

            # Step 7: Update AdsAccount.last_sync_at and sync_status
            ads_account.last_sync_at = datetime.now(timezone.utc)
            ads_account.sync_status = "completed"
            session.add(ads_account)
            session.commit()

            # Step 8: Return count of campaigns and keywords synced
            return {
                "campaigns_synced": campaigns_count,
                "keywords_synced": keywords_count
            }

    except Exception as e:
        # Update ads_account status on error
        try:
            with Session(engine) as session:
                project = session.get(Project, uuid.UUID(project_id))
                if project and project.ads_account:
                    project.ads_account.sync_status = "error"
                    session.add(project.ads_account)
                    session.commit()
        except Exception:
            pass

        return {"error": str(e)}
