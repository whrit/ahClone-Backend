"""SERP/Rank Tracking API routes."""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    KeywordTarget,
    KeywordTargetCreate,
    KeywordTargetPublic,
    KeywordTargetsPublic,
    Message,
    Project,
    RankHistoryResponse,
    RankObservationPublic,
    SerpResultPublic,
    SerpSnapshot,
    SerpSnapshotPublic,
    SerpSnapshotsPublic,
)
from app.services.serp.providers import provider_registry
from app.services.serp.tracker import RankTracker
from app.tasks.serp import refresh_keyword, refresh_project_keywords

router = APIRouter(prefix="/projects/{project_id}/serp", tags=["serp"])


def get_project_or_404(session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser) -> Project:
    """
    Get project by ID and verify ownership.

    Args:
        session: Database session
        project_id: Project UUID
        current_user: Current authenticated user

    Returns:
        Project instance

    Raises:
        HTTPException: If project not found or user doesn't own it
    """
    project = session.get(Project, project_id)
    if not project or project.created_by_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/providers", response_model=list[dict[str, Any]])
def list_providers(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    List available SERP providers.

    Returns list of provider information dictionaries with keys:
    - key: Provider key
    - name: Display name
    - is_compliant: Compliance status
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Return available providers from registry
    return provider_registry.list_available(compliant_only=True)


@router.post("/keywords", response_model=KeywordTargetPublic)
def add_keyword(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_in: KeywordTargetCreate,
) -> KeywordTarget:
    """
    Add a keyword to track.

    Checks:
    - MAX_KEYWORDS_PER_PROJECT limit
    - Duplicate (same keyword+locale+device)

    Creates KeywordTarget and triggers refresh_keyword.delay()
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Check MAX_KEYWORDS_PER_PROJECT limit
    count_statement = (
        select(func.count())
        .select_from(KeywordTarget)
        .where(KeywordTarget.project_id == project_id)
    )
    keyword_count = session.exec(count_statement).one()

    if keyword_count >= settings.MAX_KEYWORDS_PER_PROJECT:
        raise HTTPException(
            status_code=400,
            detail=f"Project keyword limit reached ({settings.MAX_KEYWORDS_PER_PROJECT} keywords max)"
        )

    # Check for duplicate (same keyword+locale+device)
    duplicate_statement = (
        select(KeywordTarget)
        .where(KeywordTarget.project_id == project_id)
        .where(KeywordTarget.keyword == keyword_in.keyword)
        .where(KeywordTarget.locale == keyword_in.locale)
        .where(KeywordTarget.device == keyword_in.device)
    )
    duplicate = session.exec(duplicate_statement).first()

    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"Already tracking keyword '{keyword_in.keyword}' for {keyword_in.locale}/{keyword_in.device}"
        )

    # Create KeywordTarget
    keyword_target = KeywordTarget(
        project_id=project_id,
        **keyword_in.model_dump()
    )
    session.add(keyword_target)
    session.commit()
    session.refresh(keyword_target)

    # Trigger refresh_keyword.delay()
    refresh_keyword.delay(str(keyword_target.id))

    return keyword_target


@router.get("/keywords", response_model=KeywordTargetsPublic)
def list_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> KeywordTargetsPublic:
    """
    List tracked keywords with pagination.

    Query parameters:
    - skip: Number of records to skip (default: 0)
    - limit: Max number of records to return (default: 100)
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Count total keywords
    count_statement = (
        select(func.count())
        .select_from(KeywordTarget)
        .where(KeywordTarget.project_id == project_id)
    )
    count = session.exec(count_statement).one()

    # Get keywords with pagination
    statement = (
        select(KeywordTarget)
        .where(KeywordTarget.project_id == project_id)
        .offset(skip)
        .limit(limit)
    )
    keywords = session.exec(statement).all()

    return KeywordTargetsPublic(data=list(keywords), count=count)


@router.delete("/keywords/{keyword_id}")
def delete_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> Message:
    """
    Delete a tracked keyword.

    Cascade deletes observations and snapshots.
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Delete keyword (cascade will handle observations and snapshots)
    session.delete(keyword)
    session.commit()

    return Message(message="Keyword deleted successfully")


@router.post("/keywords/{keyword_id}/refresh")
def refresh_keyword_manual(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> Message:
    """
    Trigger manual refresh for a keyword.

    Queues refresh_keyword.delay()
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Queue refresh task
    refresh_keyword.delay(str(keyword_id))

    return Message(message="Keyword refresh queued")


@router.post("/refresh-all")
def refresh_all(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
) -> Message:
    """
    Trigger refresh for all project keywords.

    Queues refresh_project_keywords.delay()
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Queue refresh task
    refresh_project_keywords.delay(str(project_id))

    return Message(message="Project keywords refresh queued")


@router.get("/keywords/{keyword_id}/history", response_model=RankHistoryResponse)
def get_rank_history(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    days: int = 30,
) -> RankHistoryResponse:
    """
    Get rank history for a keyword.

    Query parameters:
    - days: Number of days of history (default: 30, max: 90)

    Returns:
    - RankHistoryResponse with trend data for charts
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Clamp days to max of 90
    days = min(days, 90)

    # Create RankTracker and get history
    tracker = RankTracker(session=session)
    observations = tracker.get_rank_history(keyword_id, days=days)

    # Convert to public models
    public_observations = [
        RankObservationPublic(
            id=obs.id,
            keyword_target_id=obs.keyword_target_id,
            observed_at=obs.observed_at,
            rank=obs.rank,
            url=obs.url,
            domain=obs.domain,
            title=obs.title,
            snippet=obs.snippet,
            status=obs.status,
        )
        for obs in observations
    ]

    return RankHistoryResponse(data=public_observations, count=len(public_observations))


@router.get("/keywords/{keyword_id}/snapshots/latest", response_model=SerpSnapshotPublic)
def get_latest_snapshot(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> SerpSnapshotPublic:
    """
    Get latest snapshot for a keyword.

    Returns the most recent SERP snapshot ordered by captured_at.
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Get latest snapshot
    statement = (
        select(SerpSnapshot)
        .where(SerpSnapshot.keyword_target_id == keyword_id)
        .order_by(SerpSnapshot.captured_at.desc())
        .limit(1)
    )
    snapshot = session.exec(statement).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshots found for this keyword")

    # Convert snapshot to public model
    results = []
    organic_results = snapshot.results_json.get("organic", [])

    for result in organic_results:
        results.append(
            SerpResultPublic(
                position=result.get("position", 0),
                url=result.get("url", ""),
                domain=result.get("domain", ""),
                title=result.get("title", ""),
                snippet=result.get("snippet", ""),
                displayed_url=result.get("displayed_url"),
            )
        )

    return SerpSnapshotPublic(
        id=snapshot.id,
        keyword_target_id=snapshot.keyword_target_id,
        captured_at=snapshot.captured_at,
        results=results,
        total_results=snapshot.total_results,
    )


@router.get("/keywords/{keyword_id}/snapshots/{snapshot_id}", response_model=SerpSnapshotPublic)
def get_serp_snapshot(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> SerpSnapshotPublic:
    """
    Get a SERP snapshot.

    Marks is_own_domain for results matching project.seed_url domain.
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Get snapshot and verify it belongs to this keyword
    snapshot = session.get(SerpSnapshot, snapshot_id)
    if not snapshot or snapshot.keyword_target_id != keyword_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    # Convert snapshot to public model
    results = []
    organic_results = snapshot.results_json.get("organic", [])

    for result in organic_results:
        results.append(
            SerpResultPublic(
                position=result.get("position", 0),
                url=result.get("url", ""),
                domain=result.get("domain", ""),
                title=result.get("title", ""),
                snippet=result.get("snippet", ""),
                displayed_url=result.get("displayed_url"),
            )
        )

    return SerpSnapshotPublic(
        id=snapshot.id,
        keyword_target_id=snapshot.keyword_target_id,
        captured_at=snapshot.captured_at,
        results=results,
        total_results=snapshot.total_results,
    )


@router.get("/keywords/{keyword_id}", response_model=KeywordTargetPublic)
def get_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> KeywordTarget:
    """
    Get single keyword details.

    Returns full KeywordTarget data including latest position and metadata.
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    return keyword


@router.get("/keywords/{keyword_id}/snapshots", response_model=SerpSnapshotsPublic)
def list_keyword_snapshots(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> SerpSnapshotsPublic:
    """
    List snapshots for a keyword with pagination.

    Query parameters:
    - skip: Number of records to skip (default: 0)
    - limit: Max number of records to return (default: 100)

    Returns snapshots ordered by captured_at descending (newest first).
    """
    # Verify project exists and user has access
    get_project_or_404(session, project_id, current_user)

    # Get keyword and verify it belongs to this project
    keyword = session.get(KeywordTarget, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(status_code=404, detail="Keyword not found")

    # Count total snapshots
    count_statement = (
        select(func.count())
        .select_from(SerpSnapshot)
        .where(SerpSnapshot.keyword_target_id == keyword_id)
    )
    count = session.exec(count_statement).one()

    # Get snapshots with pagination, ordered by captured_at descending
    statement = (
        select(SerpSnapshot)
        .where(SerpSnapshot.keyword_target_id == keyword_id)
        .order_by(SerpSnapshot.captured_at.desc())
        .offset(skip)
        .limit(limit)
    )
    snapshots = session.exec(statement).all()

    # Convert to public models
    public_snapshots = []
    for snapshot in snapshots:
        results = []
        organic_results = snapshot.results_json.get("organic", [])

        for result in organic_results:
            results.append(
                SerpResultPublic(
                    position=result.get("position", 0),
                    url=result.get("url", ""),
                    domain=result.get("domain", ""),
                    title=result.get("title", ""),
                    snippet=result.get("snippet", ""),
                    displayed_url=result.get("displayed_url"),
                )
            )

        public_snapshots.append(
            SerpSnapshotPublic(
                id=snapshot.id,
                keyword_target_id=snapshot.keyword_target_id,
                captured_at=snapshot.captured_at,
                results=results,
                total_results=snapshot.total_results,
            )
        )

    return SerpSnapshotsPublic(data=public_snapshots, count=count)
