"""
TDD Tests for Links Models (Sprint 4: Backlinks)

This test file is written FIRST following TDD principles.
All tests should FAIL initially until the models are implemented.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

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
    NewLostLink,
    NewLostResponse,
    OverlapDomain,
    OverlapResponse,
    RefDomainAgg,
    RefDomainRow,
    RefDomainsResponse,
)


class TestLinkSnapshot:
    """Test LinkSnapshot model - tracks CommonCrawl ingestion snapshots."""

    def test_link_snapshot_creation_with_defaults(self, db: Session):
        """Test creating a LinkSnapshot with default values."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.id is not None
        assert isinstance(snapshot.id, uuid.UUID)
        assert snapshot.source == "commoncrawl"
        assert snapshot.crawl_id == "CC-MAIN-2024-10"
        assert snapshot.subset_spec == {}
        assert snapshot.status == "pending"
        assert snapshot.error_message is None
        assert snapshot.edges_count == 0
        assert snapshot.domains_count == 0
        assert snapshot.duration_seconds is None
        assert isinstance(snapshot.ingested_at, datetime)

    def test_link_snapshot_with_all_fields(self, db: Session):
        """Test creating a LinkSnapshot with all fields populated."""
        ingested_time = datetime.now(timezone.utc)
        snapshot = LinkSnapshot(
            source="commoncrawl",
            crawl_id="CC-MAIN-2024-10",
            subset_spec={"segments": ["1", "2", "3"], "filter": "*.example.com"},
            ingested_at=ingested_time,
            status="completed",
            error_message=None,
            edges_count=1000000,
            domains_count=50000,
            duration_seconds=3600,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.source == "commoncrawl"
        assert snapshot.crawl_id == "CC-MAIN-2024-10"
        assert snapshot.subset_spec == {
            "segments": ["1", "2", "3"],
            "filter": "*.example.com",
        }
        assert snapshot.ingested_at == ingested_time
        assert snapshot.status == "completed"
        assert snapshot.edges_count == 1000000
        assert snapshot.domains_count == 50000
        assert snapshot.duration_seconds == 3600

    def test_link_snapshot_status_transitions(self, db: Session):
        """Test LinkSnapshot status field can transition through different states."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.status == "pending"

        snapshot.status = "ingesting"
        db.add(snapshot)
        db.commit()
        assert snapshot.status == "ingesting"

        snapshot.status = "completed"
        db.add(snapshot)
        db.commit()
        assert snapshot.status == "completed"

    def test_link_snapshot_failed_status_with_error(self, db: Session):
        """Test LinkSnapshot with failed status and error message."""
        snapshot = LinkSnapshot(
            source="commoncrawl",
            crawl_id="CC-MAIN-2024-10",
            status="failed",
            error_message="Network timeout while fetching segment 5",
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.status == "failed"
        assert snapshot.error_message == "Network timeout while fetching segment 5"

    def test_link_snapshot_query_by_crawl_id(self, db: Session):
        """Test querying LinkSnapshots by crawl_id."""
        snapshot1 = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        snapshot2 = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-11")
        snapshot3 = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")

        db.add(snapshot1)
        db.add(snapshot2)
        db.add(snapshot3)
        db.commit()

        results = db.exec(
            select(LinkSnapshot).where(LinkSnapshot.crawl_id == "CC-MAIN-2024-10")
        ).all()

        assert len(results) == 2
        assert all(s.crawl_id == "CC-MAIN-2024-10" for s in results)


class TestBacklinkEdge:
    """Test BacklinkEdge model - individual backlink records."""

    def test_backlink_edge_creation_minimal(self, db: Session):
        """Test creating a BacklinkEdge with minimal required fields."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        backlink = BacklinkEdge(
            snapshot_id=snapshot.id,
            source_url="https://blog.example.com/article",
            target_url="https://target.com/page",
            source_domain="blog.example.com",
            target_domain="target.com",
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(backlink)
        db.commit()
        db.refresh(backlink)

        assert backlink.id is not None
        assert isinstance(backlink.id, uuid.UUID)
        assert backlink.snapshot_id == snapshot.id
        assert backlink.source_url == "https://blog.example.com/article"
        assert backlink.target_url == "https://target.com/page"
        assert backlink.source_domain == "blog.example.com"
        assert backlink.target_domain == "target.com"
        assert backlink.anchor_text is None
        assert backlink.is_nofollow is False
        assert backlink.is_sponsored is False
        assert backlink.is_ugc is False

    def test_backlink_edge_with_all_fields(self, db: Session):
        """Test creating a BacklinkEdge with all fields populated."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        backlink = BacklinkEdge(
            snapshot_id=snapshot.id,
            source_url="https://blog.example.com/article",
            target_url="https://target.com/page",
            source_domain="blog.example.com",
            target_domain="target.com",
            anchor_text="Click here for more info",
            is_nofollow=True,
            is_sponsored=False,
            is_ugc=False,
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(backlink)
        db.commit()
        db.refresh(backlink)

        assert backlink.anchor_text == "Click here for more info"
        assert backlink.is_nofollow is True
        assert backlink.is_sponsored is False
        assert backlink.is_ugc is False

    def test_backlink_edge_sponsored_ugc_flags(self, db: Session):
        """Test BacklinkEdge with sponsored and UGC flags."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        backlink = BacklinkEdge(
            snapshot_id=snapshot.id,
            source_url="https://forum.example.com/post/123",
            target_url="https://target.com/page",
            source_domain="forum.example.com",
            target_domain="target.com",
            anchor_text="User-generated link",
            is_nofollow=True,
            is_sponsored=False,
            is_ugc=True,
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(backlink)
        db.commit()
        db.refresh(backlink)

        assert backlink.is_ugc is True
        assert backlink.is_sponsored is False

    def test_backlink_edge_foreign_key_constraint(self, db: Session):
        """Test BacklinkEdge enforces foreign key constraint to LinkSnapshot."""
        non_existent_snapshot_id = uuid.uuid4()
        first_seen = datetime.now(timezone.utc)

        backlink = BacklinkEdge(
            snapshot_id=non_existent_snapshot_id,
            source_url="https://example.com",
            target_url="https://target.com",
            source_domain="example.com",
            target_domain="target.com",
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(backlink)

        with pytest.raises(IntegrityError):
            db.commit()

    def test_backlink_edge_index_on_target_domain(self, db: Session):
        """Test BacklinkEdge has index on target_domain for efficient queries."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        for i in range(5):
            backlink = BacklinkEdge(
                snapshot_id=snapshot.id,
                source_url=f"https://source{i}.com/page",
                target_url="https://target.com/page",
                source_domain=f"source{i}.com",
                target_domain="target.com",
                first_seen=first_seen,
                last_seen=first_seen,
            )
            db.add(backlink)
        db.commit()

        results = db.exec(
            select(BacklinkEdge).where(BacklinkEdge.target_domain == "target.com")
        ).all()

        assert len(results) == 5

    def test_backlink_edge_index_on_source_domain(self, db: Session):
        """Test BacklinkEdge has index on source_domain for efficient queries."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        for i in range(3):
            backlink = BacklinkEdge(
                snapshot_id=snapshot.id,
                source_url="https://source.com/page",
                target_url=f"https://target{i}.com/page",
                source_domain="source.com",
                target_domain=f"target{i}.com",
                first_seen=first_seen,
                last_seen=first_seen,
            )
            db.add(backlink)
        db.commit()

        results = db.exec(
            select(BacklinkEdge).where(BacklinkEdge.source_domain == "source.com")
        ).all()

        assert len(results) == 3

    def test_backlink_edge_cascade_delete_with_snapshot(self, db: Session):
        """Test BacklinkEdge is deleted when associated LinkSnapshot is deleted."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        backlink = BacklinkEdge(
            snapshot_id=snapshot.id,
            source_url="https://example.com",
            target_url="https://target.com",
            source_domain="example.com",
            target_domain="target.com",
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(backlink)
        db.commit()
        snapshot_id = snapshot.id

        db.delete(snapshot)
        db.commit()

        # Backlink should be deleted due to CASCADE
        result = db.exec(
            select(BacklinkEdge).where(BacklinkEdge.snapshot_id == snapshot_id)
        ).first()
        assert result is None


class TestRefDomainAgg:
    """Test RefDomainAgg model - referring domain aggregations."""

    def test_ref_domain_agg_creation(self, db: Session):
        """Test creating a RefDomainAgg record."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        ref_domain = RefDomainAgg(
            snapshot_id=snapshot.id,
            target_domain="target.com",
            ref_domain="referring.com",
            backlinks_count=5,
            dofollow_count=3,
            nofollow_count=2,
            first_seen=first_seen,
            last_seen=first_seen,
            top_anchors=["anchor1", "anchor2"],
        )
        db.add(ref_domain)
        db.commit()
        db.refresh(ref_domain)

        assert ref_domain.id is not None
        assert isinstance(ref_domain.id, uuid.UUID)
        assert ref_domain.snapshot_id == snapshot.id
        assert ref_domain.target_domain == "target.com"
        assert ref_domain.ref_domain == "referring.com"
        assert ref_domain.backlinks_count == 5
        assert ref_domain.dofollow_count == 3
        assert ref_domain.nofollow_count == 2
        assert ref_domain.top_anchors == ["anchor1", "anchor2"]

    def test_ref_domain_agg_defaults(self, db: Session):
        """Test RefDomainAgg default values."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        ref_domain = RefDomainAgg(
            snapshot_id=snapshot.id,
            target_domain="target.com",
            ref_domain="referring.com",
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(ref_domain)
        db.commit()
        db.refresh(ref_domain)

        assert ref_domain.backlinks_count == 1
        assert ref_domain.dofollow_count == 0
        assert ref_domain.nofollow_count == 0
        assert ref_domain.top_anchors == []

    def test_ref_domain_agg_index_on_target_domain(self, db: Session):
        """Test RefDomainAgg has index on target_domain."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        first_seen = datetime.now(timezone.utc)
        for i in range(3):
            ref_domain = RefDomainAgg(
                snapshot_id=snapshot.id,
                target_domain="target.com",
                ref_domain=f"ref{i}.com",
                first_seen=first_seen,
                last_seen=first_seen,
            )
            db.add(ref_domain)
        db.commit()

        results = db.exec(
            select(RefDomainAgg).where(RefDomainAgg.target_domain == "target.com")
        ).all()

        assert len(results) == 3

    def test_ref_domain_agg_foreign_key_constraint(self, db: Session):
        """Test RefDomainAgg enforces foreign key constraint."""
        non_existent_snapshot_id = uuid.uuid4()
        first_seen = datetime.now(timezone.utc)

        ref_domain = RefDomainAgg(
            snapshot_id=non_existent_snapshot_id,
            target_domain="target.com",
            ref_domain="ref.com",
            first_seen=first_seen,
            last_seen=first_seen,
        )
        db.add(ref_domain)

        with pytest.raises(IntegrityError):
            db.commit()


class TestAnchorAgg:
    """Test AnchorAgg model - anchor text aggregations."""

    def test_anchor_agg_creation(self, db: Session):
        """Test creating an AnchorAgg record."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        anchor = AnchorAgg(
            snapshot_id=snapshot.id,
            target_domain="target.com",
            anchor_text="Click here",
            backlinks_count=10,
            ref_domains_count=5,
        )
        db.add(anchor)
        db.commit()
        db.refresh(anchor)

        assert anchor.id is not None
        assert isinstance(anchor.id, uuid.UUID)
        assert anchor.snapshot_id == snapshot.id
        assert anchor.target_domain == "target.com"
        assert anchor.anchor_text == "Click here"
        assert anchor.backlinks_count == 10
        assert anchor.ref_domains_count == 5

    def test_anchor_agg_defaults(self, db: Session):
        """Test AnchorAgg default values."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        anchor = AnchorAgg(
            snapshot_id=snapshot.id,
            target_domain="target.com",
            anchor_text="Default anchor",
        )
        db.add(anchor)
        db.commit()
        db.refresh(anchor)

        assert anchor.backlinks_count == 1
        assert anchor.ref_domains_count == 1

    def test_anchor_agg_index_on_target_domain(self, db: Session):
        """Test AnchorAgg has index on target_domain."""
        snapshot = LinkSnapshot(source="commoncrawl", crawl_id="CC-MAIN-2024-10")
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        for i in range(3):
            anchor = AnchorAgg(
                snapshot_id=snapshot.id,
                target_domain="target.com",
                anchor_text=f"Anchor {i}",
            )
            db.add(anchor)
        db.commit()

        results = db.exec(
            select(AnchorAgg).where(AnchorAgg.target_domain == "target.com")
        ).all()

        assert len(results) == 3


class TestAPIResponseModels:
    """Test API response models for Links feature."""

    def test_ref_domain_row_creation(self):
        """Test RefDomainRow response model."""
        row = RefDomainRow(
            ref_domain="example.com",
            backlinks=100,
            dofollow=80,
            nofollow=20,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        assert row.ref_domain == "example.com"
        assert row.backlinks == 100
        assert row.dofollow == 80
        assert row.nofollow == 20

    def test_ref_domains_response_creation(self):
        """Test RefDomainsResponse response model."""
        row1 = RefDomainRow(
            ref_domain="example.com",
            backlinks=100,
            dofollow=80,
            nofollow=20,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        row2 = RefDomainRow(
            ref_domain="test.com",
            backlinks=50,
            dofollow=40,
            nofollow=10,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        response = RefDomainsResponse(data=[row1, row2], total=2)
        assert len(response.data) == 2
        assert response.total == 2

    def test_backlink_row_creation(self):
        """Test BacklinkRow response model."""
        row = BacklinkRow(
            source_url="https://example.com/page",
            target_url="https://target.com/page",
            source_domain="example.com",
            anchor_text="Click here",
            is_nofollow=False,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        assert row.source_url == "https://example.com/page"
        assert row.target_url == "https://target.com/page"
        assert row.anchor_text == "Click here"
        assert row.is_nofollow is False

    def test_backlinks_response_creation(self):
        """Test BacklinksResponse response model."""
        row = BacklinkRow(
            source_url="https://example.com/page",
            target_url="https://target.com/page",
            source_domain="example.com",
            anchor_text="Click here",
            is_nofollow=False,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        response = BacklinksResponse(data=[row], total=1)
        assert len(response.data) == 1
        assert response.total == 1

    def test_anchor_row_creation(self):
        """Test AnchorRow response model."""
        row = AnchorRow(anchor_text="Click here", backlinks=100, ref_domains=50)
        assert row.anchor_text == "Click here"
        assert row.backlinks == 100
        assert row.ref_domains == 50

    def test_anchors_response_creation(self):
        """Test AnchorsResponse response model."""
        row1 = AnchorRow(anchor_text="Click here", backlinks=100, ref_domains=50)
        row2 = AnchorRow(anchor_text="Read more", backlinks=80, ref_domains=40)
        response = AnchorsResponse(data=[row1, row2], total=2)
        assert len(response.data) == 2
        assert response.total == 2

    def test_new_lost_link_creation(self):
        """Test NewLostLink response model."""
        link = NewLostLink(
            source_url="https://example.com/page",
            target_url="https://target.com/page",
            source_domain="example.com",
            anchor_text="Click here",
            is_nofollow=False,
            date=datetime.now(timezone.utc),
        )
        assert link.source_url == "https://example.com/page"
        assert link.anchor_text == "Click here"

    def test_new_lost_response_creation(self):
        """Test NewLostResponse response model."""
        link = NewLostLink(
            source_url="https://example.com/page",
            target_url="https://target.com/page",
            source_domain="example.com",
            anchor_text="Click here",
            is_nofollow=False,
            date=datetime.now(timezone.utc),
        )
        response = NewLostResponse(data=[link], total=1)
        assert len(response.data) == 1
        assert response.total == 1

    def test_overlap_domain_creation(self):
        """Test OverlapDomain response model."""
        domain = OverlapDomain(
            domain="example.com", links_to_a=10, links_to_b=15, total_backlinks=100
        )
        assert domain.domain == "example.com"
        assert domain.links_to_a == 10
        assert domain.links_to_b == 15
        assert domain.total_backlinks == 100

    def test_overlap_response_creation(self):
        """Test OverlapResponse response model."""
        domain = OverlapDomain(
            domain="example.com", links_to_a=10, links_to_b=15, total_backlinks=100
        )
        response = OverlapResponse(data=[domain], total=1)
        assert len(response.data) == 1
        assert response.total == 1

    def test_intersect_domain_creation(self):
        """Test IntersectDomain response model."""
        domain = IntersectDomain(
            domain="example.com",
            backlinks_count=50,
            dofollow_count=40,
            nofollow_count=10,
        )
        assert domain.domain == "example.com"
        assert domain.backlinks_count == 50
        assert domain.dofollow_count == 40
        assert domain.nofollow_count == 10

    def test_intersect_response_creation(self):
        """Test IntersectResponse response model."""
        domain = IntersectDomain(
            domain="example.com",
            backlinks_count=50,
            dofollow_count=40,
            nofollow_count=10,
        )
        response = IntersectResponse(data=[domain], total=1)
        assert len(response.data) == 1
        assert response.total == 1
