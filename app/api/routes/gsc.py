"""GSC (Google Search Console) API routes."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc as sql_desc
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.oauth.google import GoogleOAuthClient
from app.models.gsc import (
    ClusterPublic,
    GSCPageDaily,
    GSCPageRow,
    GSCPagesResponse,
    GSCProperty,
    GSCPropertyPublic,
    GSCQueriesResponse,
    GSCQueryDaily,
    GSCQueryRow,
    KeywordCluster,
    OpportunitiesResponse,
    OpportunityRow,
)
from app.models.integration import IntegrationAccount
from app.models.project import Project
from app.services.gsc.client import GSCClient
from app.services.gsc.opportunities import OpportunityFinder
from app.tasks.gsc import backfill_gsc_data, cluster_queries, sync_gsc_property

router = APIRouter(prefix="/projects/{project_id}/gsc", tags=["gsc"])


# ==================== Request/Response Models ====================


class LinkPropertyRequest(BaseModel):
    """Request model for linking a GSC property."""
    site_url: str


class TaskResponse(BaseModel):
    """Response model for async task triggers."""
    message: str
    task_id: str


class BackfillTaskResponse(TaskResponse):
    """Response model for backfill task."""
    days: int


class ClustersResponse(BaseModel):
    """Response model for keyword clusters."""
    data: list[ClusterPublic]
    count: int


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
    Get Google GSC integration account for user.

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
        IntegrationAccount.provider == "google_gsc"
    )
    account = session.exec(stmt).first()
    if not account:
        raise HTTPException(
            status_code=404,
            detail="Integration account not found. Please connect your Google account first."
        )
    return account


def get_gsc_property_or_404(
    session: SessionDep, project_id: uuid.UUID
) -> GSCProperty:
    """
    Get GSC property for project.

    Args:
        session: Database session
        project_id: Project UUID

    Returns:
        GSCProperty instance

    Raises:
        HTTPException: If GSC property not found
    """
    stmt = select(GSCProperty).where(GSCProperty.project_id == project_id)
    gsc_property = session.exec(stmt).first()
    if not gsc_property:
        raise HTTPException(
            status_code=404,
            detail="GSC property not found. Please link a property first."
        )
    return gsc_property


async def get_gsc_client(
    session: SessionDep, user_id: uuid.UUID
) -> GSCClient:
    """
    Create GSC client with user's OAuth tokens.

    Args:
        session: Database session
        user_id: User UUID

    Returns:
        Configured GSCClient instance
    """
    account = get_integration_account_or_404(session, user_id)
    oauth_client = GoogleOAuthClient()

    # Decrypt tokens
    access_token = oauth_client.decrypt_token(account.access_token_encrypted)
    refresh_token = oauth_client.decrypt_token(account.refresh_token_encrypted)

    # Check if token is expired and refresh if needed
    # Make comparison timezone-aware
    now = datetime.now(timezone.utc)
    token_expiry = account.token_expires_at
    if token_expiry.tzinfo is None:
        token_expiry = token_expiry.replace(tzinfo=timezone.utc)

    if token_expiry < now:
        token_response = await oauth_client.refresh_token(refresh_token)
        access_token = token_response["access_token"]
        expires_in = token_response.get("expires_in", 3600)

        # Update account with new token
        account.access_token_encrypted = oauth_client.encrypt_token(access_token)
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in
        )
        session.add(account)
        session.commit()

    return GSCClient(access_token=access_token, refresh_token=refresh_token)


# ==================== API Routes ====================


@router.get("/properties")
async def list_available_properties(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    List GSC properties available to link from Google API.

    Returns properties the user has access to in Google Search Console.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        List of available properties with siteUrl and permissionLevel
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Get GSC client
    gsc_client = await get_gsc_client(session, current_user.id)

    # Fetch sites from Google API
    sites = await gsc_client.list_sites()

    return sites


@router.post("/link", response_model=GSCPropertyPublic)
async def link_property(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request: LinkPropertyRequest,
) -> GSCProperty:
    """
    Link a GSC property to the project.

    Creates a GSCProperty record linking the project to a Google Search Console property.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        request: Link property request with site_url

    Returns:
        Created GSCProperty instance
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Check if property already linked
    existing_stmt = select(GSCProperty).where(GSCProperty.project_id == project_id)
    existing_property = session.exec(existing_stmt).first()
    if existing_property:
        raise HTTPException(
            status_code=400,
            detail="Project already has a GSC property linked. Please unlink first."
        )

    # Get GSC client
    gsc_client = await get_gsc_client(session, current_user.id)

    # Verify site exists and user has access
    site_info = await gsc_client.get_site(request.site_url)

    # Create GSC property
    gsc_property = GSCProperty(
        project_id=project_id,
        site_url=request.site_url,
        permission_level=site_info.get("permissionLevel"),
        verified=True,
        linked_at=datetime.now(timezone.utc),
        sync_status="pending",
        search_type="web",
    )

    session.add(gsc_property)
    session.commit()
    session.refresh(gsc_property)

    return gsc_property


@router.delete("/unlink")
def unlink_property(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> dict[str, str]:
    """
    Unlink the GSC property from project.

    Removes the GSC property link. This will cascade delete all GSC data.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        Success message
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Get GSC property
    gsc_property = get_gsc_property_or_404(session, project_id)

    # Delete property (cascade will remove related data)
    session.delete(gsc_property)
    session.commit()

    return {"message": "GSC property unlinked successfully"}


@router.post("/sync", response_model=TaskResponse)
def trigger_sync(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> TaskResponse:
    """
    Trigger manual GSC sync.

    Queues a Celery task to sync GSC data for the project.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        Task response with task_id
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify GSC property exists
    get_gsc_property_or_404(session, project_id)

    # Queue sync task
    task = sync_gsc_property.delay(str(project_id))

    return TaskResponse(
        message="Sync task queued",
        task_id=task.id,
    )


@router.post("/backfill", response_model=BackfillTaskResponse)
def trigger_backfill(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    days: int = Query(default=90, ge=1, le=365),
) -> BackfillTaskResponse:
    """
    Trigger GSC data backfill.

    Queues a Celery task to backfill historical GSC data.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        days: Number of days to backfill (1-365, default 90)

    Returns:
        Task response with task_id and days
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify GSC property exists
    get_gsc_property_or_404(session, project_id)

    # Queue backfill task
    task = backfill_gsc_data.delay(str(project_id), days)

    return BackfillTaskResponse(
        message="Backfill task queued",
        task_id=task.id,
        days=days,
    )


@router.get("/queries", response_model=GSCQueriesResponse)
def get_queries(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    search: str | None = None,
    sort_by: str = Query(default="clicks", pattern="^(clicks|impressions|ctr|position)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    period_days: int = Query(default=28, ge=1, le=90),
) -> GSCQueriesResponse:
    """
    Get query explorer data with aggregation.

    Returns aggregated query performance data for the specified period.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        search: Optional search filter for query text
        sort_by: Field to sort by (clicks, impressions, ctr, position)
        sort_order: Sort order (asc, desc)
        period_days: Number of days to aggregate (1-90)

    Returns:
        GSCQueriesResponse with aggregated query data
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Calculate date range
    end_date = date.today() - timedelta(days=3)  # GSC data has ~3 day delay
    start_date = end_date - timedelta(days=period_days - 1)

    # Build column references - type: ignore needed for SQLAlchemy label inference
    total_clicks: Any = func.sum(GSCQueryDaily.clicks).label("total_clicks")
    total_impressions: Any = func.sum(GSCQueryDaily.impressions).label("total_impressions")
    avg_ctr: Any = func.avg(GSCQueryDaily.ctr).label("avg_ctr")
    avg_position: Any = func.avg(GSCQueryDaily.position).label("avg_position")

    # Build aggregation query
    query_stmt = (
        select(  # type: ignore[call-overload]
            GSCQueryDaily.query,
            total_clicks,
            total_impressions,
            avg_ctr,
            avg_position,
        )
        .where(GSCQueryDaily.project_id == project_id)
        .where(GSCQueryDaily.date >= start_date)
        .where(GSCQueryDaily.date <= end_date)
        .group_by(GSCQueryDaily.query)
    )

    # Apply search filter
    if search:
        query_stmt = query_stmt.where(GSCQueryDaily.query.contains(search))  # type: ignore[attr-defined]

    # Get count before pagination
    count_stmt = select(func.count()).select_from(
        query_stmt.subquery()
    )
    count = session.exec(count_stmt).one()

    # Apply sorting
    sort_column = {
        "clicks": total_clicks,
        "impressions": total_impressions,
        "ctr": avg_ctr,
        "position": avg_position,
    }[sort_by]

    if sort_order == "asc":
        query_stmt = query_stmt.order_by(sort_column)
    else:
        query_stmt = query_stmt.order_by(sql_desc(sort_column))

    # Apply pagination
    query_stmt = query_stmt.offset(skip).limit(limit)

    # Execute query
    results = session.exec(query_stmt).all()

    # Build response
    data = [
        GSCQueryRow(
            query=row.query,
            clicks=row.total_clicks,
            impressions=row.total_impressions,
            ctr=row.avg_ctr,
            position=row.avg_position,
        )
        for row in results
    ]

    return GSCQueriesResponse(data=data, count=count)


@router.get("/pages", response_model=GSCPagesResponse)
def get_pages(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    search: str | None = None,
    sort_by: str = Query(default="clicks", pattern="^(clicks|impressions|ctr|position)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    period_days: int = Query(default=28, ge=1, le=90),
) -> GSCPagesResponse:
    """
    Get page explorer data.

    Returns aggregated page performance data for the specified period.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        search: Optional search filter for page URL
        sort_by: Field to sort by (clicks, impressions, ctr, position)
        sort_order: Sort order (asc, desc)
        period_days: Number of days to aggregate (1-90)

    Returns:
        GSCPagesResponse with aggregated page data
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Calculate date range
    end_date = date.today() - timedelta(days=3)
    start_date = end_date - timedelta(days=period_days - 1)

    # Build column references - type: ignore needed for SQLAlchemy label inference
    total_clicks: Any = func.sum(GSCPageDaily.clicks).label("total_clicks")
    total_impressions: Any = func.sum(GSCPageDaily.impressions).label("total_impressions")
    avg_ctr: Any = func.avg(GSCPageDaily.ctr).label("avg_ctr")
    avg_position: Any = func.avg(GSCPageDaily.position).label("avg_position")

    # Build aggregation query
    page_stmt = (
        select(  # type: ignore[call-overload]
            GSCPageDaily.page,
            total_clicks,
            total_impressions,
            avg_ctr,
            avg_position,
        )
        .where(GSCPageDaily.project_id == project_id)
        .where(GSCPageDaily.date >= start_date)
        .where(GSCPageDaily.date <= end_date)
        .group_by(GSCPageDaily.page)
    )

    # Apply search filter
    if search:
        page_stmt = page_stmt.where(GSCPageDaily.page.contains(search))  # type: ignore[attr-defined]

    # Get count before pagination
    count_stmt = select(func.count()).select_from(
        page_stmt.subquery()
    )
    count = session.exec(count_stmt).one()

    # Apply sorting
    sort_column = {
        "clicks": total_clicks,
        "impressions": total_impressions,
        "ctr": avg_ctr,
        "position": avg_position,
    }[sort_by]

    if sort_order == "asc":
        page_stmt = page_stmt.order_by(sort_column)
    else:
        page_stmt = page_stmt.order_by(sql_desc(sort_column))

    # Apply pagination
    page_stmt = page_stmt.offset(skip).limit(limit)

    # Execute query
    results = session.exec(page_stmt).all()

    # Build response
    data = [
        GSCPageRow(
            page=row.page,
            clicks=row.total_clicks,
            impressions=row.total_impressions,
            ctr=row.avg_ctr,
            position=row.avg_position,
        )
        for row in results
    ]

    return GSCPagesResponse(data=data, count=count)


@router.get("/opportunities", response_model=OpportunitiesResponse)
def get_opportunities(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    opportunity_type: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> OpportunitiesResponse:
    """
    Get keyword opportunities.

    Analyzes GSC data to identify SEO opportunities like low CTR queries,
    position 8-20 queries, rising/falling keywords.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        opportunity_type: Optional filter by type (low_ctr, position_8_20, rising, falling)
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return

    Returns:
        OpportunitiesResponse with identified opportunities
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Create opportunity finder
    finder = OpportunityFinder(session=session)

    # Find opportunities
    opportunities = list(finder.find_opportunities(project_id=project_id))

    # Filter by type if specified
    if opportunity_type:
        opportunities = [
            opp for opp in opportunities
            if opp.opportunity_type.value == opportunity_type
        ]

    # Sort by score (descending)
    opportunities.sort(key=lambda x: x.score, reverse=True)

    # Get total count
    count = len(opportunities)

    # Apply pagination
    opportunities = opportunities[skip:skip + limit]

    # Convert to response model
    data = [
        OpportunityRow(
            query=opp.query,
            impressions=opp.impressions,
            clicks=opp.clicks,
            ctr=opp.ctr,
            position=opp.position,
            opportunity_type=opp.opportunity_type.value,
            potential_clicks=int(opp.score),  # Simplified potential calculation
        )
        for opp in opportunities
    ]

    return OpportunitiesResponse(data=data, count=count)


@router.get("/clusters", response_model=ClustersResponse)
def get_clusters(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> ClustersResponse:
    """
    Get keyword clusters.

    Returns keyword clusters generated from query data.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return

    Returns:
        ClustersResponse with keyword clusters
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Get count
    count_stmt = (
        select(func.count())
        .select_from(KeywordCluster)
        .where(KeywordCluster.project_id == project_id)
    )
    count = session.exec(count_stmt).one()

    # Get clusters
    stmt = (
        select(KeywordCluster)
        .where(KeywordCluster.project_id == project_id)
        .order_by(sql_desc(KeywordCluster.total_clicks))  # type: ignore[arg-type]
        .offset(skip)
        .limit(limit)
    )
    clusters = session.exec(stmt).all()

    # Convert to public model
    data = [
        ClusterPublic(
            id=cluster.id,
            project_id=cluster.project_id,
            label=cluster.label,
            algorithm=cluster.algorithm,
            created_at=cluster.created_at,
            total_clicks=cluster.total_clicks,
            total_impressions=cluster.total_impressions,
            avg_position=cluster.avg_position,
            query_count=cluster.query_count,
        )
        for cluster in clusters
    ]

    return ClustersResponse(data=data, count=count)


@router.post("/clusters/generate", response_model=TaskResponse)
def generate_clusters(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> TaskResponse:
    """
    Regenerate keyword clusters.

    Queues a Celery task to generate keyword clusters from query data.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        Task response with task_id
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Verify GSC property exists
    get_gsc_property_or_404(session, project_id)

    # Queue cluster task
    task = cluster_queries.delay(str(project_id))

    return TaskResponse(
        message="Cluster generation task queued",
        task_id=task.id,
    )
