"""Traffic API routes for Sprint 5: PPC + Traffic."""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.ads import TrafficDaily, TrafficPanelResponse, TrafficPanelRow
from app.models.gsc import GSCQueryDaily
from app.models.project import Project
from app.services.traffic.panel import TrafficPanelService

router = APIRouter(prefix="/projects/{project_id}/traffic", tags=["traffic"])


# ==================== Request/Response Models ====================


class CSVImportRequest(BaseModel):
    """Request model for CSV import."""

    csv_data: list[dict]


class CSVImportResponse(BaseModel):
    """Response model for CSV import."""

    imported: int


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


# ==================== API Routes ====================


@router.get("/panel", response_model=TrafficPanelResponse)
def get_traffic_panel(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    period_days: int = Query(default=28, ge=1, le=90),
) -> TrafficPanelResponse:
    """
    Get combined traffic panel data from multiple sources.

    Aggregates traffic data from:
    - GA4 (sessions, users, pageviews from TrafficDaily with source_key='ga4')
    - GSC (organic clicks from GSCQueryDaily)
    - CrUX (Core Web Vitals from TrafficDaily with source_key='crux')
    - CSV (custom uploaded data from TrafficDaily with source_key='csv')

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        period_days: Number of days to retrieve (1-90, default 28)

    Returns:
        TrafficPanelResponse with time series data
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Get panel data from service
    service = TrafficPanelService(session)
    panel_data = service.get_panel_data(project_id, period_days)

    # Convert to response model
    data = [
        TrafficPanelRow(
            date=row["date"],
            sessions=row.get("ga4_sessions"),
            users=row.get("ga4_users"),
            pageviews=row.get("ga4_pageviews"),
            bounce_rate=None,  # Not currently tracked
            avg_session_duration=None,  # Not currently tracked
            organic_clicks=row.get("gsc_clicks"),
            paid_clicks=None,  # TODO: Add paid clicks from AdsCampaignDaily
        )
        for row in panel_data
    ]

    return TrafficPanelResponse(data=data, total=len(data))


@router.post("/import-csv", response_model=CSVImportResponse)
def import_csv(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request: CSVImportRequest,
) -> CSVImportResponse:
    """
    Import traffic data from CSV.

    Creates TrafficDaily records with source_key='csv' from the provided CSV data.
    Invalid rows are skipped gracefully.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID
        request: CSV import request with csv_data

    Returns:
        CSVImportResponse with count of imported records
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    # Import CSV data using service
    service = TrafficPanelService(session)
    imported_count = service.import_csv_data(project_id, request.csv_data)

    return CSVImportResponse(imported=imported_count)


@router.get("/sources")
def get_available_sources(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> list[str]:
    """
    Get list of available traffic sources for this project.

    Returns unique source keys from both TrafficDaily and GSC data.

    Args:
        session: Database session
        current_user: Current authenticated user
        project_id: Project UUID

    Returns:
        List of unique source keys (e.g., ['ga4', 'gsc', 'crux', 'csv'])
    """
    # Verify user has access to project
    get_project_or_404(session, project_id, current_user)

    sources = set()

    # Get sources from TrafficDaily
    stmt = (
        select(TrafficDaily.source_key)
        .where(TrafficDaily.project_id == project_id)
        .distinct()
    )
    traffic_sources = session.exec(stmt).all()
    sources.update(traffic_sources)

    # Check if GSC data exists
    gsc_stmt = (
        select(GSCQueryDaily.id)
        .where(GSCQueryDaily.project_id == project_id)
        .limit(1)
    )
    gsc_exists = session.exec(gsc_stmt).first()
    if gsc_exists:
        sources.add("gsc")

    return sorted(list(sources))
