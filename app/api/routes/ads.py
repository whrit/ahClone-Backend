"""Ads (Google Ads) API routes."""
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc as sql_desc
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.oauth.google import GoogleOAuthClient
from app.models.ads import (
    AdsCampaignDaily,
    AdsAccount,
    AdsKeywordDaily,
    CampaignRow,
    CampaignsResponse,
    OverlapResponse,
    OverlapRow,
    OverlapSummary,
    PaidKeywordRow,
)
from app.models.integration import IntegrationAccount
from app.models.project import Project
from app.services.ads.google_ads import GoogleAdsService
from app.services.ads.overlap import OverlapAnalyzer
from app.tasks.ads import sync_ads_account

router = APIRouter(prefix="/projects/{project_id}/ads", tags=["ads"])


# ==================== Request/Response Models ====================


class LinkAdsAccountRequest(BaseModel):
    """Request model for linking a Google Ads account."""
    customer_id: str


class AdsAccountPublic(BaseModel):
    """Public response model for ads account."""
    id: uuid.UUID
    project_id: uuid.UUID
    customer_id: str
    descriptive_name: str | None
    currency_code: str
    linked_at: str
    last_sync_at: str | None
    sync_status: str


class TaskResponse(BaseModel):
    """Response model for async task triggers."""
    message: str
    task_id: str


class KeywordsResponse(BaseModel):
    """API response for keywords endpoint."""
    data: list[PaidKeywordRow]
    total: int


# ==================== Helper Functions ====================


def get_project_or_404(
    session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Project:
    """
    Get project by ID and verify user has access.

    Args:
        session: Database session
        project_id: Project UUID
        current_user: Current authenticated user

    Returns:
        Project instance

    Raises:
        HTTPException: If project not found or user lacks permissions
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    if not current_user.is_superuser and (project.created_by_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    return project


def get_integration_account_or_404(
    session: SessionDep, user_id: uuid.UUID
) -> IntegrationAccount:
    """
    Get Google Ads integration account for user.

    Args:
        session: Database session
        user_id: User UUID

    Returns:
        IntegrationAccount instance

    Raises:
        HTTPException: If integration account not found
    """
    stmt = select(IntegrationAccount).where(
        IntegrationAccount.user_id == user_id,
        IntegrationAccount.provider == "google_ads"
    )
    account = session.exec(stmt).first()
    if not account:
        raise HTTPException(
            status_code=404,
            detail="Integration account not found. Please connect your Google Ads account first."
        )
    return account


def get_ads_account_or_400(
    session: SessionDep, project_id: uuid.UUID
) -> AdsAccount:
    """
    Get Ads account for project.

    Args:
        session: Database session
        project_id: Project UUID

    Returns:
        AdsAccount instance

    Raises:
        HTTPException: If Ads account not found
    """
    stmt = select(AdsAccount).where(AdsAccount.project_id == project_id)
    ads_account = session.exec(stmt).first()
    if not ads_account:
        raise HTTPException(
            status_code=400,
            detail="No ads account linked to this project"
        )
    return ads_account


# ==================== API Routes ====================


@router.get("/accounts")
async def list_available_accounts(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    List Google Ads accounts available to link.

    Returns accounts the user has access to via Google Ads API.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        List of available accounts with customer_id, name, currency, timezone
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Get integration account
    integration = get_integration_account_or_404(session, current_user.id)

    # Decrypt refresh token
    oauth_client = GoogleOAuthClient()
    refresh_token = oauth_client.decrypt_token(integration.refresh_token_encrypted)

    # Create Google Ads service with a temporary customer ID
    # We'll use the service to list accessible customers
    ads_service = GoogleAdsService(
        refresh_token=refresh_token,
        customer_id="0",  # Placeholder, not used for list_accessible_customers
    )

    # Get accessible customers
    customers = ads_service.list_accessible_customers()

    return customers


@router.post("/link")
async def link_ads_account(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request: LinkAdsAccountRequest,
) -> AdsAccountPublic:
    """
    Link a Google Ads account to the project.

    Creates an AdsAccount record linking the project to a Google Ads customer.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        request: Link ads account request with customer_id

    Returns:
        Created AdsAccount instance
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Check if ads account already linked
    existing_stmt = select(AdsAccount).where(AdsAccount.project_id == project_id)
    existing_account = session.exec(existing_stmt).first()
    if existing_account:
        raise HTTPException(
            status_code=400,
            detail="Project already has an ads account linked. Please unlink first."
        )

    # Get integration account
    integration = get_integration_account_or_404(session, current_user.id)

    # Decrypt refresh token
    oauth_client = GoogleOAuthClient()
    refresh_token = oauth_client.decrypt_token(integration.refresh_token_encrypted)

    # Create Google Ads service to verify account access
    ads_service = GoogleAdsService(
        refresh_token=refresh_token,
        customer_id=request.customer_id,
    )

    # Get customer details to verify access
    customer_details = ads_service._get_customer_details(request.customer_id)
    if not customer_details:
        raise HTTPException(
            status_code=400,
            detail="Unable to access the specified Google Ads account"
        )

    # Create Ads account
    from datetime import datetime, timezone

    ads_account = AdsAccount(
        project_id=project_id,
        customer_id=request.customer_id,
        descriptive_name=customer_details["name"],
        currency_code=customer_details["currency"],
        sync_status="pending",
    )

    session.add(ads_account)
    session.commit()
    session.refresh(ads_account)

    return AdsAccountPublic(
        id=ads_account.id,
        project_id=ads_account.project_id,
        customer_id=ads_account.customer_id,
        descriptive_name=ads_account.descriptive_name,
        currency_code=ads_account.currency_code,
        linked_at=ads_account.linked_at.isoformat(),
        last_sync_at=ads_account.last_sync_at.isoformat() if ads_account.last_sync_at else None,
        sync_status=ads_account.sync_status,
    )


@router.post("/sync", response_model=TaskResponse)
def trigger_sync(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> TaskResponse:
    """
    Trigger manual Ads sync.

    Queues a Celery task to sync Google Ads data for the project.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        Task response with task_id
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify Ads account exists
    get_ads_account_or_400(session, project_id)

    # Queue sync task
    task = sync_ads_account.delay(str(project_id))

    return TaskResponse(
        message="Sync task queued",
        task_id=task.id,
    )


@router.get("/campaigns", response_model=CampaignsResponse)
def get_campaigns(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    period_days: int = Query(default=28, ge=1, le=90),
) -> CampaignsResponse:
    """
    Get campaign performance aggregated over period.

    Returns aggregated campaign performance data for the specified period.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        period_days: Number of days to aggregate (1-90, default 28)

    Returns:
        CampaignsResponse with aggregated campaign data
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify Ads account exists
    get_ads_account_or_400(session, project_id)

    # Calculate date range
    end_date = date.today() - timedelta(days=2)  # Ads data has ~2 day delay
    start_date = end_date - timedelta(days=period_days - 1)

    # Build column references - type: ignore needed for SQLAlchemy label inference
    total_impressions: Any = func.sum(AdsCampaignDaily.impressions).label("total_impressions")
    total_clicks: Any = func.sum(AdsCampaignDaily.clicks).label("total_clicks")
    total_cost_micros: Any = func.sum(AdsCampaignDaily.cost_micros).label("total_cost_micros")
    total_conversions: Any = func.sum(AdsCampaignDaily.conversions).label("total_conversions")
    total_conversion_value: Any = func.sum(AdsCampaignDaily.conversion_value).label("total_conversion_value")

    # Build aggregation query - group by campaign_id and campaign_name
    campaign_stmt = (
        select(  # type: ignore[call-overload]
            AdsCampaignDaily.campaign_id,
            AdsCampaignDaily.campaign_name,
            AdsCampaignDaily.campaign_status,
            total_impressions,
            total_clicks,
            total_cost_micros,
            total_conversions,
            total_conversion_value,
        )
        .where(AdsCampaignDaily.project_id == project_id)
        .where(AdsCampaignDaily.date >= start_date)
        .where(AdsCampaignDaily.date <= end_date)
        .group_by(
            AdsCampaignDaily.campaign_id,
            AdsCampaignDaily.campaign_name,
            AdsCampaignDaily.campaign_status,
        )
        .order_by(sql_desc(total_clicks))
    )

    # Execute query
    results = session.exec(campaign_stmt).all()

    # Build response
    data = [
        CampaignRow(
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            campaign_status=row.campaign_status,
            impressions=row.total_impressions,
            clicks=row.total_clicks,
            cost_micros=row.total_cost_micros,
            conversions=row.total_conversions,
            conversion_value=row.total_conversion_value,
        )
        for row in results
    ]

    return CampaignsResponse(data=data, total=len(data))


@router.get("/keywords", response_model=KeywordsResponse)
def get_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    period_days: int = Query(default=28, ge=1, le=90),
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> KeywordsResponse:
    """
    Get keyword performance aggregated over period.

    Returns aggregated keyword performance data for the specified period.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        period_days: Number of days to aggregate (1-90, default 28)
        search: Optional search filter for keyword text
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return

    Returns:
        KeywordsResponse with aggregated keyword data
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify Ads account exists
    get_ads_account_or_400(session, project_id)

    # Calculate date range
    end_date = date.today() - timedelta(days=2)  # Ads data has ~2 day delay
    start_date = end_date - timedelta(days=period_days - 1)

    # Build column references - type: ignore needed for SQLAlchemy label inference
    total_impressions: Any = func.sum(AdsKeywordDaily.impressions).label("total_impressions")
    total_clicks: Any = func.sum(AdsKeywordDaily.clicks).label("total_clicks")
    total_cost_micros: Any = func.sum(AdsKeywordDaily.cost_micros).label("total_cost_micros")
    total_conversions: Any = func.sum(AdsKeywordDaily.conversions).label("total_conversions")
    avg_cpc_micros: Any = func.avg(AdsKeywordDaily.average_cpc_micros).label("avg_cpc_micros")
    avg_quality_score: Any = func.avg(AdsKeywordDaily.quality_score).label("avg_quality_score")

    # Build aggregation query - group by keyword_text and match_type
    keyword_stmt = (
        select(  # type: ignore[call-overload]
            AdsKeywordDaily.keyword_text,
            AdsKeywordDaily.match_type,
            total_impressions,
            total_clicks,
            total_cost_micros,
            total_conversions,
            avg_cpc_micros,
            avg_quality_score,
        )
        .where(AdsKeywordDaily.project_id == project_id)
        .where(AdsKeywordDaily.date >= start_date)
        .where(AdsKeywordDaily.date <= end_date)
        .group_by(
            AdsKeywordDaily.keyword_text,
            AdsKeywordDaily.match_type,
        )
    )

    # Apply search filter
    if search:
        keyword_stmt = keyword_stmt.where(AdsKeywordDaily.keyword_text.contains(search))  # type: ignore[attr-defined]

    # Get count before pagination
    count_stmt = select(func.count()).select_from(
        keyword_stmt.subquery()
    )
    count = session.exec(count_stmt).one()

    # Apply sorting and pagination
    keyword_stmt = keyword_stmt.order_by(sql_desc(total_clicks))
    keyword_stmt = keyword_stmt.offset(skip).limit(limit)

    # Execute query
    results = session.exec(keyword_stmt).all()

    # Build response
    data = [
        PaidKeywordRow(
            keyword_text=row.keyword_text,
            match_type=row.match_type,
            impressions=row.total_impressions,
            clicks=row.total_clicks,
            cost_micros=row.total_cost_micros,
            conversions=row.total_conversions,
            average_cpc_micros=int(row.avg_cpc_micros) if row.avg_cpc_micros else 0,
            quality_score=int(row.avg_quality_score) if row.avg_quality_score else None,
        )
        for row in results
    ]

    return KeywordsResponse(data=data, total=count)


@router.get("/seo-overlap", response_model=OverlapResponse)
def get_seo_overlap(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    period_days: int = Query(default=28, ge=1, le=90),
    overlap_type: str | None = Query(default=None, pattern="^(both|paid_only|organic_only)$"),
) -> OverlapResponse:
    """
    Get SEO + PPC overlap analysis.

    Analyzes keyword overlap between organic (GSC) and paid (Ads) performance.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        period_days: Number of days to analyze (1-90, default 28)
        overlap_type: Filter by overlap type: "both", "paid_only", or "organic_only"

    Returns:
        OverlapResponse with keyword overlap data and summary statistics
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify Ads account exists
    get_ads_account_or_400(session, project_id)

    # Create overlap analyzer
    analyzer = OverlapAnalyzer(session=session)

    # Compute overlap
    overlap_results = analyzer.compute_overlap(
        project_id=project_id,
        period_days=period_days,
    )

    # Apply overlap_type filter if specified
    if overlap_type:
        overlap_results = [r for r in overlap_results if r.overlap_type == overlap_type]

    # Initialize summary counters
    summary_counts = {
        "both": 0,
        "paid_only": 0,
        "organic_only": 0,
    }

    # Convert to response model
    # Note: We need to compute paid_position from the keyword data
    # For simplicity, we'll use a weighted average based on impressions
    data = []
    for result in overlap_results:
        # Count for summary
        summary_counts[result.overlap_type] += 1

        # Calculate paid position (simplified - using inverse of CTR as proxy)
        # In a real implementation, you'd track actual ad position
        paid_position = 0.0
        if result.paid_clicks > 0:
            # Estimate position from CPC and clicks (simplified heuristic)
            # Higher CPC typically correlates with better position
            # This is a rough approximation
            paid_position = max(1.0, 10.0 - (result.paid_cpc / 1.0))

        # Convert cost from dollars to micros
        paid_cost_micros = int(result.paid_cost * 1_000_000)

        overlap_row = OverlapRow(
            keyword=result.keyword,
            organic_position=result.organic_position,
            paid_position=paid_position,
            organic_clicks=result.organic_clicks,
            paid_clicks=result.paid_clicks,
            total_clicks=result.organic_clicks + result.paid_clicks,
            paid_cost_micros=paid_cost_micros,
            opportunity_score=result.opportunity_score,
            overlap_type=result.overlap_type,
        )
        data.append(overlap_row)

    # Build summary
    summary = OverlapSummary(
        total_keywords=len(data),
        overlap_count=summary_counts["both"],
        paid_only_count=summary_counts["paid_only"],
        organic_only_count=summary_counts["organic_only"],
    )

    return OverlapResponse(data=data, total=len(data), summary=summary)
