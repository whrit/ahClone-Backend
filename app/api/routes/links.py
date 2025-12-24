"""
Links (Backlinks) API routes for Sprint 4.

Provides endpoints for:
- Referring domains analysis
- Backlinks listing
- Anchor text distribution
- Competitive overlap analysis
- Link building opportunities (intersect)
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import desc, func, select

from app.api.deps import SessionDep
from app.models.links import (
    AnchorAgg,
    AnchorRow,
    AnchorsResponse,
    BacklinkEdge,
    BacklinkRow,
    BacklinksResponse,
    IntersectDomain,
    IntersectResponse,
    LinkSnapshot,
    OverlapDomain,
    OverlapResponse,
    RefDomainAgg,
    RefDomainRow,
    RefDomainsResponse,
)
from app.services.links.competitive import CompetitiveAnalyzer

router = APIRouter(prefix="/links", tags=["links"])


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain name for consistent matching.

    - Convert to lowercase
    - Remove 'www.' prefix

    Args:
        domain: The domain name to normalize

    Returns:
        Normalized domain name
    """
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def get_latest_snapshot(session: SessionDep) -> uuid.UUID | None:
    """
    Get the most recent completed snapshot.

    Args:
        session: Database session

    Returns:
        The snapshot ID if found, None otherwise
    """
    stmt = (
        select(LinkSnapshot.id)
        .where(LinkSnapshot.status == "completed")
        .order_by(desc(LinkSnapshot.ingested_at))
        .limit(1)
    )
    return session.exec(stmt).first()


@router.get("/domain/{domain}/refdomains", response_model=RefDomainsResponse)
def get_refdomains(
    session: SessionDep,
    domain: str,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Get referring domains for a target domain.

    Returns a list of domains that link to the target domain,
    along with backlink counts and dofollow/nofollow splits.

    Args:
        domain: Target domain to analyze
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return (pagination)

    Returns:
        RefDomainsResponse with referring domain data
    """
    # Get latest completed snapshot
    snapshot_id = get_latest_snapshot(session)
    if not snapshot_id:
        raise HTTPException(
            status_code=404,
            detail="No completed link snapshot found",
        )

    # Normalize domain
    normalized_domain = normalize_domain(domain)

    # Count total referring domains
    count_stmt = (
        select(func.count())
        .select_from(RefDomainAgg)
        .where(RefDomainAgg.snapshot_id == snapshot_id)
        .where(RefDomainAgg.target_domain == normalized_domain)
    )
    total = session.exec(count_stmt).one()

    # Get referring domains with pagination
    stmt = (
        select(RefDomainAgg)
        .where(RefDomainAgg.snapshot_id == snapshot_id)
        .where(RefDomainAgg.target_domain == normalized_domain)
        .offset(skip)
        .limit(limit)
    )
    ref_domains = session.exec(stmt).all()

    # Map to response model
    data = [
        RefDomainRow(
            ref_domain=rd.ref_domain,
            backlinks=rd.backlinks_count,
            dofollow=rd.dofollow_count,
            nofollow=rd.nofollow_count,
            first_seen=rd.first_seen,
            last_seen=rd.last_seen,
        )
        for rd in ref_domains
    ]

    return RefDomainsResponse(data=data, total=total)


@router.get("/domain/{domain}/backlinks", response_model=BacklinksResponse)
def get_backlinks(
    session: SessionDep,
    domain: str,
    ref_domain: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Get backlinks for a target domain.

    Returns individual backlink records (source URL -> target URL pairs).
    Optionally filter by referring domain.

    Args:
        domain: Target domain to analyze
        ref_domain: Optional filter by referring domain
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return (pagination)

    Returns:
        BacklinksResponse with backlink data
    """
    # Get latest completed snapshot
    snapshot_id = get_latest_snapshot(session)
    if not snapshot_id:
        raise HTTPException(
            status_code=404,
            detail="No completed link snapshot found",
        )

    # Normalize domains
    normalized_domain = normalize_domain(domain)
    normalized_ref_domain = normalize_domain(ref_domain) if ref_domain else None

    # Build query
    count_stmt = (
        select(func.count())
        .select_from(BacklinkEdge)
        .where(BacklinkEdge.snapshot_id == snapshot_id)
        .where(BacklinkEdge.target_domain == normalized_domain)
    )
    stmt = (
        select(BacklinkEdge)
        .where(BacklinkEdge.snapshot_id == snapshot_id)
        .where(BacklinkEdge.target_domain == normalized_domain)
    )

    # Apply ref_domain filter if provided
    if normalized_ref_domain:
        count_stmt = count_stmt.where(
            BacklinkEdge.source_domain == normalized_ref_domain
        )
        stmt = stmt.where(BacklinkEdge.source_domain == normalized_ref_domain)

    # Get total count
    total = session.exec(count_stmt).one()

    # Get backlinks with pagination
    stmt = stmt.offset(skip).limit(limit)
    backlinks = session.exec(stmt).all()

    # Map to response model
    data = [
        BacklinkRow(
            source_url=bl.source_url,
            target_url=bl.target_url,
            source_domain=bl.source_domain,
            anchor_text=bl.anchor_text,
            is_nofollow=bl.is_nofollow,
            first_seen=bl.first_seen,
            last_seen=bl.last_seen,
        )
        for bl in backlinks
    ]

    return BacklinksResponse(data=data, total=total)


@router.get("/domain/{domain}/anchors", response_model=AnchorsResponse)
def get_anchors(
    session: SessionDep,
    domain: str,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Get anchor text distribution for a target domain.

    Returns anchor texts used in backlinks along with
    backlink and referring domain counts.

    Args:
        domain: Target domain to analyze
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return (pagination)

    Returns:
        AnchorsResponse with anchor text data
    """
    # Get latest completed snapshot
    snapshot_id = get_latest_snapshot(session)
    if not snapshot_id:
        raise HTTPException(
            status_code=404,
            detail="No completed link snapshot found",
        )

    # Normalize domain
    normalized_domain = normalize_domain(domain)

    # Count total anchor texts
    count_stmt = (
        select(func.count())
        .select_from(AnchorAgg)
        .where(AnchorAgg.snapshot_id == snapshot_id)
        .where(AnchorAgg.target_domain == normalized_domain)
    )
    total = session.exec(count_stmt).one()

    # Get anchor texts with pagination
    stmt = (
        select(AnchorAgg)
        .where(AnchorAgg.snapshot_id == snapshot_id)
        .where(AnchorAgg.target_domain == normalized_domain)
        .offset(skip)
        .limit(limit)
    )
    anchors = session.exec(stmt).all()

    # Map to response model
    data = [
        AnchorRow(
            anchor_text=anchor.anchor_text,
            backlinks=anchor.backlinks_count,
            ref_domains=anchor.ref_domains_count,
        )
        for anchor in anchors
    ]

    return AnchorsResponse(data=data, total=total)


@router.get("/domain/{domain}/overlap", response_model=OverlapResponse)
def get_overlap(
    session: SessionDep,
    domain: str,
    competitors: str = Query(
        ..., description="Comma-separated list of competitor domains"
    ),
) -> Any:
    """
    Find domains that link to both target and competitors.

    This identifies shared referring domains, which can indicate
    industry-relevant sites or partnership opportunities.

    Args:
        domain: Target domain to analyze
        competitors: Comma-separated list of competitor domains

    Returns:
        OverlapResponse with shared referring domains
    """
    # Get latest completed snapshot
    snapshot_id = get_latest_snapshot(session)
    if not snapshot_id:
        raise HTTPException(
            status_code=404,
            detail="No completed link snapshot found",
        )

    # Normalize domains
    normalized_domain = normalize_domain(domain)
    competitor_list = [normalize_domain(c.strip()) for c in competitors.split(",")]

    # Use CompetitiveAnalyzer
    analyzer = CompetitiveAnalyzer(session)
    overlap_results = analyzer.compute_overlap(
        target_domain=normalized_domain,
        competitor_domains=competitor_list,
        snapshot_id=snapshot_id,
    )

    # Map to response model
    data = [
        OverlapDomain(
            domain=result["domain"],
            links_to_a=result["links_to_you"],
            links_to_b=sum(result["links_to_competitors"].values()),
            total_backlinks=result["links_to_you"]
            + sum(result["links_to_competitors"].values()),
        )
        for result in overlap_results
    ]

    return OverlapResponse(data=data, total=len(data))


@router.get("/domain/{domain}/intersect", response_model=IntersectResponse)
def get_intersect(
    session: SessionDep,
    domain: str,
    competitors: str = Query(
        ..., description="Comma-separated list of competitor domains"
    ),
) -> Any:
    """
    Find domains that link to competitors but NOT to target.

    These are link building opportunities - sites that already link
    to similar/competing content but haven't linked to the target yet.

    Args:
        domain: Target domain to analyze
        competitors: Comma-separated list of competitor domains

    Returns:
        IntersectResponse with link building opportunities
    """
    # Get latest completed snapshot
    snapshot_id = get_latest_snapshot(session)
    if not snapshot_id:
        raise HTTPException(
            status_code=404,
            detail="No completed link snapshot found",
        )

    # Normalize domains
    normalized_domain = normalize_domain(domain)
    competitor_list = [normalize_domain(c.strip()) for c in competitors.split(",")]

    # Use CompetitiveAnalyzer
    analyzer = CompetitiveAnalyzer(session)
    intersect_results = analyzer.compute_intersect(
        target_domain=normalized_domain,
        competitor_domains=competitor_list,
        snapshot_id=snapshot_id,
    )

    # Map to response model
    data = [
        IntersectDomain(
            domain=result["domain"],
            backlinks_count=result["total_links"],
            dofollow_count=0,  # Not tracked in current implementation
            nofollow_count=0,  # Not tracked in current implementation
        )
        for result in intersect_results
    ]

    return IntersectResponse(data=data, total=len(data))
