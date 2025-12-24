"""
Tests for Links API routes (Sprint 4: Backlinks).
"""

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models.links import (
    AnchorAgg,
    BacklinkEdge,
    LinkSnapshot,
    RefDomainAgg,
)


def create_link_snapshot(session: Session, status: str = "completed") -> LinkSnapshot:
    """Create a test link snapshot."""
    snapshot = LinkSnapshot(
        source="commoncrawl",
        crawl_id="CC-MAIN-2024-10",
        subset_spec={},
        status=status,
        edges_count=100,
        domains_count=50,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def create_backlink_edges(
    session: Session,
    snapshot_id: uuid.UUID,
    target_domain: str,
    source_domains: list[str],
) -> list[BacklinkEdge]:
    """Create test backlink edges."""
    edges = []
    now = datetime.now(timezone.utc)

    for i, source_domain in enumerate(source_domains):
        edge = BacklinkEdge(
            snapshot_id=snapshot_id,
            source_url=f"https://{source_domain}/page-{i}",
            target_url=f"https://{target_domain}/target-{i}",
            source_domain=source_domain,
            target_domain=target_domain,
            anchor_text=f"anchor text {i}",
            is_nofollow=(i % 2 == 0),
            first_seen=now,
            last_seen=now,
        )
        edges.append(edge)
        session.add(edge)

    session.commit()
    for edge in edges:
        session.refresh(edge)
    return edges


def create_ref_domain_aggs(
    session: Session,
    snapshot_id: uuid.UUID,
    target_domain: str,
    ref_domains: list[str],
) -> list[RefDomainAgg]:
    """Create test ref domain aggregations."""
    aggs = []
    now = datetime.now(timezone.utc)

    for i, ref_domain in enumerate(ref_domains):
        agg = RefDomainAgg(
            snapshot_id=snapshot_id,
            target_domain=target_domain,
            ref_domain=ref_domain,
            backlinks_count=i + 1,
            dofollow_count=i,
            nofollow_count=1,
            first_seen=now,
            last_seen=now,
            top_anchors=[f"anchor {i}"],
        )
        aggs.append(agg)
        session.add(agg)

    session.commit()
    for agg in aggs:
        session.refresh(agg)
    return aggs


def create_anchor_aggs(
    session: Session,
    snapshot_id: uuid.UUID,
    target_domain: str,
    anchors: list[str],
) -> list[AnchorAgg]:
    """Create test anchor aggregations."""
    aggs = []

    for i, anchor_text in enumerate(anchors):
        agg = AnchorAgg(
            snapshot_id=snapshot_id,
            target_domain=target_domain,
            anchor_text=anchor_text,
            backlinks_count=i + 1,
            ref_domains_count=i + 1,
        )
        aggs.append(agg)
        session.add(agg)

    session.commit()
    for agg in aggs:
        session.refresh(agg)
    return aggs


def test_get_refdomains(client: TestClient, db: Session) -> None:
    """Test GET /links/domain/{domain}/refdomains endpoint."""
    # Create snapshot and data
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    ref_domains = ["ref1.com", "ref2.com", "ref3.com"]
    create_ref_domain_aggs(db, snapshot.id, target_domain, ref_domains)

    # Test endpoint
    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/refdomains"
    )
    assert response.status_code == 200
    content = response.json()

    assert "data" in content
    assert "total" in content
    assert content["total"] == 3
    assert len(content["data"]) == 3

    # Verify structure of first item
    first_item = content["data"][0]
    assert "ref_domain" in first_item
    assert "backlinks" in first_item
    assert "dofollow" in first_item
    assert "nofollow" in first_item
    assert "first_seen" in first_item
    assert "last_seen" in first_item


def test_get_refdomains_with_pagination(client: TestClient, db: Session) -> None:
    """Test refdomains endpoint with pagination."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    ref_domains = [f"ref{i}.com" for i in range(10)]
    create_ref_domain_aggs(db, snapshot.id, target_domain, ref_domains)

    # Test with skip and limit
    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/refdomains?skip=2&limit=3"
    )
    assert response.status_code == 200
    content = response.json()

    assert content["total"] == 10
    assert len(content["data"]) == 3


def test_get_refdomains_no_snapshot(client: TestClient, db: Session) -> None:
    """Test refdomains endpoint when no completed snapshot exists."""
    # Clean up all snapshots to ensure test isolation
    from sqlmodel import delete

    db.execute(delete(LinkSnapshot))
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/links/domain/example.com/refdomains")
    assert response.status_code == 404
    content = response.json()
    assert "snapshot" in content["detail"].lower()


def test_get_refdomains_normalizes_domain(client: TestClient, db: Session) -> None:
    """Test that domain names are normalized (lowercase, no www)."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    ref_domains = ["ref1.com"]
    create_ref_domain_aggs(db, snapshot.id, target_domain, ref_domains)

    # Test with uppercase and www
    response = client.get(
        f"{settings.API_V1_STR}/links/domain/WWW.EXAMPLE.COM/refdomains"
    )
    assert response.status_code == 200
    content = response.json()
    assert content["total"] == 1


def test_get_backlinks(client: TestClient, db: Session) -> None:
    """Test GET /links/domain/{domain}/backlinks endpoint."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    source_domains = ["source1.com", "source2.com", "source3.com"]
    create_backlink_edges(db, snapshot.id, target_domain, source_domains)

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/backlinks"
    )
    assert response.status_code == 200
    content = response.json()

    assert "data" in content
    assert "total" in content
    assert content["total"] == 3
    assert len(content["data"]) == 3

    # Verify structure
    first_item = content["data"][0]
    assert "source_url" in first_item
    assert "target_url" in first_item
    assert "source_domain" in first_item
    assert "anchor_text" in first_item
    assert "is_nofollow" in first_item
    assert "first_seen" in first_item
    assert "last_seen" in first_item


def test_get_backlinks_with_ref_domain_filter(client: TestClient, db: Session) -> None:
    """Test backlinks endpoint with ref_domain filter."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    source_domains = ["source1.com", "source2.com", "source3.com"]
    create_backlink_edges(db, snapshot.id, target_domain, source_domains)

    # Filter by specific ref_domain
    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/backlinks?ref_domain=source1.com"
    )
    assert response.status_code == 200
    content = response.json()

    assert content["total"] == 1
    assert len(content["data"]) == 1
    assert content["data"][0]["source_domain"] == "source1.com"


def test_get_backlinks_with_pagination(client: TestClient, db: Session) -> None:
    """Test backlinks endpoint with pagination."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    source_domains = [f"source{i}.com" for i in range(10)]
    create_backlink_edges(db, snapshot.id, target_domain, source_domains)

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/backlinks?skip=3&limit=4"
    )
    assert response.status_code == 200
    content = response.json()

    assert content["total"] == 10
    assert len(content["data"]) == 4


def test_get_backlinks_no_snapshot(client: TestClient, db: Session) -> None:
    """Test backlinks endpoint when no completed snapshot exists."""
    # Clean up all snapshots to ensure test isolation
    from sqlmodel import delete

    db.execute(delete(BacklinkEdge))
    db.execute(delete(LinkSnapshot))
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/links/domain/example.com/backlinks")
    assert response.status_code == 404
    content = response.json()
    assert "snapshot" in content["detail"].lower()


def test_get_anchors(client: TestClient, db: Session) -> None:
    """Test GET /links/domain/{domain}/anchors endpoint."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    anchors = ["click here", "read more", "learn more"]
    create_anchor_aggs(db, snapshot.id, target_domain, anchors)

    response = client.get(f"{settings.API_V1_STR}/links/domain/{target_domain}/anchors")
    assert response.status_code == 200
    content = response.json()

    assert "data" in content
    assert "total" in content
    assert content["total"] == 3
    assert len(content["data"]) == 3

    # Verify structure
    first_item = content["data"][0]
    assert "anchor_text" in first_item
    assert "backlinks" in first_item
    assert "ref_domains" in first_item


def test_get_anchors_with_pagination(client: TestClient, db: Session) -> None:
    """Test anchors endpoint with pagination."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    anchors = [f"anchor {i}" for i in range(10)]
    create_anchor_aggs(db, snapshot.id, target_domain, anchors)

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/anchors?skip=1&limit=5"
    )
    assert response.status_code == 200
    content = response.json()

    assert content["total"] == 10
    assert len(content["data"]) == 5


def test_get_anchors_no_snapshot(client: TestClient, db: Session) -> None:
    """Test anchors endpoint when no completed snapshot exists."""
    # Clean up all snapshots to ensure test isolation
    from sqlmodel import delete

    db.execute(delete(AnchorAgg))
    db.execute(delete(LinkSnapshot))
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/links/domain/example.com/anchors")
    assert response.status_code == 404
    content = response.json()
    assert "snapshot" in content["detail"].lower()


def test_get_overlap(client: TestClient, db: Session) -> None:
    """Test GET /links/domain/{domain}/overlap endpoint."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    competitor1 = "competitor1.com"
    competitor2 = "competitor2.com"

    # Create ref domains for target and competitors
    # shared1.com links to all three
    create_ref_domain_aggs(
        db, snapshot.id, target_domain, ["shared1.com", "unique1.com"]
    )
    create_ref_domain_aggs(db, snapshot.id, competitor1, ["shared1.com", "unique2.com"])
    create_ref_domain_aggs(db, snapshot.id, competitor2, ["shared1.com", "unique3.com"])

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/overlap?competitors={competitor1},{competitor2}"
    )
    assert response.status_code == 200
    content = response.json()

    assert "data" in content
    assert "total" in content
    # Only shared1.com links to both target and competitors
    assert content["total"] == 1
    assert len(content["data"]) == 1
    assert content["data"][0]["domain"] == "shared1.com"


def test_get_overlap_no_snapshot(client: TestClient, db: Session) -> None:
    """Test overlap endpoint when no completed snapshot exists."""
    # Clean up all snapshots to ensure test isolation
    from sqlmodel import delete

    db.execute(delete(RefDomainAgg))
    db.execute(delete(LinkSnapshot))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/example.com/overlap?competitors=comp1.com,comp2.com"
    )
    assert response.status_code == 404
    content = response.json()
    assert "snapshot" in content["detail"].lower()


def test_get_intersect(client: TestClient, db: Session) -> None:
    """Test GET /links/domain/{domain}/intersect endpoint."""
    snapshot = create_link_snapshot(db)
    target_domain = "example.com"
    competitor1 = "competitor1.com"
    competitor2 = "competitor2.com"

    # Create ref domains - opportunity.com links to competitors but NOT target
    create_ref_domain_aggs(db, snapshot.id, target_domain, ["shared1.com"])
    create_ref_domain_aggs(
        db, snapshot.id, competitor1, ["shared1.com", "opportunity.com"]
    )
    create_ref_domain_aggs(
        db, snapshot.id, competitor2, ["shared1.com", "opportunity.com"]
    )

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/{target_domain}/intersect?competitors={competitor1},{competitor2}"
    )
    assert response.status_code == 200
    content = response.json()

    assert "data" in content
    assert "total" in content
    # opportunity.com is a link building opportunity
    assert content["total"] == 1
    assert len(content["data"]) == 1
    assert content["data"][0]["domain"] == "opportunity.com"


def test_get_intersect_no_snapshot(client: TestClient, db: Session) -> None:
    """Test intersect endpoint when no completed snapshot exists."""
    # Clean up all snapshots to ensure test isolation
    from sqlmodel import delete

    db.execute(delete(RefDomainAgg))
    db.execute(delete(LinkSnapshot))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/links/domain/example.com/intersect?competitors=comp1.com,comp2.com"
    )
    assert response.status_code == 404
    content = response.json()
    assert "snapshot" in content["detail"].lower()
