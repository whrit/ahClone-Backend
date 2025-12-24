"""
Test-Driven Development tests for Link Aggregation Service.
These tests are written FIRST to define the expected behavior.

Sprint 4: Backlinks - Link Aggregator
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models.links import AnchorAgg, BacklinkEdge, LinkSnapshot, RefDomainAgg
from app.services.links.aggregator import LinkAggregator


@pytest.fixture
def session() -> Session:  # type: ignore
    """Create a test database session"""
    with Session(engine) as session:
        yield session
        # Cleanup - delete test data
        session.exec(select(AnchorAgg)).all()
        for anchor_agg in session.exec(select(AnchorAgg)):
            session.delete(anchor_agg)
        for ref_agg in session.exec(select(RefDomainAgg)):
            session.delete(ref_agg)
        for edge in session.exec(select(BacklinkEdge)):
            session.delete(edge)
        for snapshot in session.exec(select(LinkSnapshot)):
            session.delete(snapshot)
        session.commit()


@pytest.fixture
def snapshot(session: Session) -> LinkSnapshot:
    """Create a test snapshot"""
    snapshot = LinkSnapshot(
        crawl_id="CC-MAIN-2024-10",
        source="commoncrawl",
        subset_spec={"test": True},
        status="completed",
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


@pytest.fixture
def target_domain() -> str:
    """Target domain for testing"""
    return "example.com"


def create_backlink_edge(
    session: Session,
    snapshot_id: uuid.UUID,
    source_domain: str,
    target_domain: str,
    anchor_text: str | None = None,
    is_nofollow: bool = False,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
) -> BacklinkEdge:
    """Helper to create a backlink edge"""
    if first_seen is None:
        first_seen = datetime.now(timezone.utc)
    if last_seen is None:
        last_seen = first_seen

    edge = BacklinkEdge(
        snapshot_id=snapshot_id,
        source_url=f"https://{source_domain}/page",
        target_url=f"https://{target_domain}/page",
        source_domain=source_domain,
        target_domain=target_domain,
        anchor_text=anchor_text,
        is_nofollow=is_nofollow,
        first_seen=first_seen,
        last_seen=last_seen,
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


class TestLinkAggregatorRefDomainAggregates:
    """Test suite for build_ref_domain_aggregates"""

    def test_creates_ref_domain_aggregates(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should create RefDomainAgg records grouped by source_domain"""
        # Create test data: 3 links from domain-a.com, 2 from domain-b.com
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "Link 1")
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "Link 2")
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "Link 3")
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "Link B1")
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "Link B2")

        aggregator = LinkAggregator(session)
        count = aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        assert count == 2  # Two distinct source domains

        # Verify aggregates were created
        aggs = session.exec(
            select(RefDomainAgg).where(RefDomainAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 2

        # Verify domain-a.com aggregate
        agg_a = next(a for a in aggs if a.ref_domain == "domain-a.com")
        assert agg_a.backlinks_count == 3
        assert agg_a.target_domain == target_domain

        # Verify domain-b.com aggregate
        agg_b = next(a for a in aggs if a.ref_domain == "domain-b.com")
        assert agg_b.backlinks_count == 2
        assert agg_b.target_domain == target_domain

    def test_calculates_dofollow_nofollow_counts(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should correctly count dofollow and nofollow links"""
        # Create 2 dofollow and 1 nofollow from same domain
        create_backlink_edge(session, snapshot.id, "test-domain.com", target_domain, "Anchor 1", is_nofollow=False)
        create_backlink_edge(session, snapshot.id, "test-domain.com", target_domain, "Anchor 2", is_nofollow=False)
        create_backlink_edge(session, snapshot.id, "test-domain.com", target_domain, "Anchor 3", is_nofollow=True)

        aggregator = LinkAggregator(session)
        count = aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        assert count == 1

        agg = session.exec(
            select(RefDomainAgg).where(
                RefDomainAgg.snapshot_id == snapshot.id,
                RefDomainAgg.ref_domain == "test-domain.com"
            )
        ).first()

        assert agg is not None
        assert agg.backlinks_count == 3
        assert agg.dofollow_count == 2
        assert agg.nofollow_count == 1

    def test_calculates_first_and_last_seen(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should calculate min(first_seen) and max(last_seen)"""
        early_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        middle_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        late_date = datetime(2024, 12, 1, tzinfo=timezone.utc)

        # Create links with different timestamps
        create_backlink_edge(
            session, snapshot.id, "time-domain.com", target_domain,
            first_seen=middle_date, last_seen=middle_date
        )
        create_backlink_edge(
            session, snapshot.id, "time-domain.com", target_domain,
            first_seen=early_date, last_seen=late_date
        )

        aggregator = LinkAggregator(session)
        aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        agg = session.exec(
            select(RefDomainAgg).where(
                RefDomainAgg.snapshot_id == snapshot.id,
                RefDomainAgg.ref_domain == "time-domain.com"
            )
        ).first()

        assert agg is not None
        assert agg.first_seen == early_date
        assert agg.last_seen == late_date

    def test_stores_top_5_anchors(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should store top 5 anchors per referring domain"""
        # Create links with various anchor texts
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor A")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor A")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor A")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor B")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor B")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor C")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor D")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor E")
        create_backlink_edge(session, snapshot.id, "anchor-domain.com", target_domain, "Anchor F")

        aggregator = LinkAggregator(session)
        aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        agg = session.exec(
            select(RefDomainAgg).where(
                RefDomainAgg.snapshot_id == snapshot.id,
                RefDomainAgg.ref_domain == "anchor-domain.com"
            )
        ).first()

        assert agg is not None
        assert len(agg.top_anchors) <= 5

        # Top anchors should be sorted by count
        # Anchor A should be first (3 occurrences)
        assert agg.top_anchors[0] == "Anchor A"

    def test_handles_null_anchors(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should handle links with null anchor text"""
        create_backlink_edge(session, snapshot.id, "null-anchor.com", target_domain, anchor_text=None)
        create_backlink_edge(session, snapshot.id, "null-anchor.com", target_domain, "Real Anchor")

        aggregator = LinkAggregator(session)
        count = aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        assert count == 1

        agg = session.exec(
            select(RefDomainAgg).where(RefDomainAgg.snapshot_id == snapshot.id)
        ).first()

        assert agg is not None
        assert agg.backlinks_count == 2

    def test_filters_by_target_domain(self, session: Session, snapshot: LinkSnapshot) -> None:
        """Should only aggregate for the specified target domain"""
        create_backlink_edge(session, snapshot.id, "source-a.com", "target-a.com", "Link")
        create_backlink_edge(session, snapshot.id, "source-b.com", "target-b.com", "Link")

        aggregator = LinkAggregator(session)
        count = aggregator.build_ref_domain_aggregates(snapshot.id, "target-a.com")

        assert count == 1

        aggs = session.exec(
            select(RefDomainAgg).where(RefDomainAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 1
        assert aggs[0].target_domain == "target-a.com"

    def test_returns_zero_for_no_backlinks(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should return 0 when no backlinks exist"""
        aggregator = LinkAggregator(session)
        count = aggregator.build_ref_domain_aggregates(snapshot.id, target_domain)

        assert count == 0


class TestLinkAggregatorAnchorAggregates:
    """Test suite for build_anchor_aggregates"""

    def test_creates_anchor_aggregates(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should create AnchorAgg records grouped by anchor_text"""
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "Anchor X")
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "Anchor X")
        create_backlink_edge(session, snapshot.id, "domain-c.com", target_domain, "Anchor Y")

        aggregator = LinkAggregator(session)
        count = aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        assert count == 2  # Two distinct anchor texts

        aggs = session.exec(
            select(AnchorAgg).where(AnchorAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 2

    def test_calculates_backlinks_count(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should count total backlinks per anchor text"""
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "Common Anchor")
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "Common Anchor")
        create_backlink_edge(session, snapshot.id, "domain-c.com", target_domain, "Common Anchor")

        aggregator = LinkAggregator(session)
        aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        agg = session.exec(
            select(AnchorAgg).where(
                AnchorAgg.snapshot_id == snapshot.id,
                AnchorAgg.anchor_text == "Common Anchor"
            )
        ).first()

        assert agg is not None
        assert agg.backlinks_count == 3

    def test_calculates_distinct_ref_domains(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should count distinct source domains per anchor text"""
        # 3 links from 2 distinct domains using same anchor
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "My Anchor")
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, "My Anchor")
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "My Anchor")

        aggregator = LinkAggregator(session)
        aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        agg = session.exec(
            select(AnchorAgg).where(
                AnchorAgg.snapshot_id == snapshot.id,
                AnchorAgg.anchor_text == "My Anchor"
            )
        ).first()

        assert agg is not None
        assert agg.backlinks_count == 3
        assert agg.ref_domains_count == 2  # Only 2 distinct domains

    def test_filters_by_target_domain(self, session: Session, snapshot: LinkSnapshot) -> None:
        """Should only aggregate for the specified target domain"""
        create_backlink_edge(session, snapshot.id, "source.com", "target-a.com", "Anchor")
        create_backlink_edge(session, snapshot.id, "source.com", "target-b.com", "Anchor")

        aggregator = LinkAggregator(session)
        count = aggregator.build_anchor_aggregates(snapshot.id, "target-a.com")

        assert count == 1

        aggs = session.exec(
            select(AnchorAgg).where(AnchorAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 1
        assert aggs[0].target_domain == "target-a.com"

    def test_skips_null_anchors(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should not create aggregates for null anchor text"""
        create_backlink_edge(session, snapshot.id, "domain-a.com", target_domain, anchor_text=None)
        create_backlink_edge(session, snapshot.id, "domain-b.com", target_domain, "Real Anchor")

        aggregator = LinkAggregator(session)
        count = aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        assert count == 1  # Only "Real Anchor" should be counted

        aggs = session.exec(
            select(AnchorAgg).where(AnchorAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 1
        assert aggs[0].anchor_text == "Real Anchor"

    def test_returns_zero_for_no_backlinks(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should return 0 when no backlinks exist"""
        aggregator = LinkAggregator(session)
        count = aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        assert count == 0

    def test_handles_empty_string_anchors(self, session: Session, snapshot: LinkSnapshot, target_domain: str) -> None:
        """Should handle empty string anchor text"""
        create_backlink_edge(session, snapshot.id, "domain.com", target_domain, anchor_text="")
        create_backlink_edge(session, snapshot.id, "domain2.com", target_domain, "Valid")

        aggregator = LinkAggregator(session)
        count = aggregator.build_anchor_aggregates(snapshot.id, target_domain)

        # Empty strings should not be aggregated (similar to null)
        assert count == 1

        aggs = session.exec(
            select(AnchorAgg).where(AnchorAgg.snapshot_id == snapshot.id)
        ).all()
        assert len(aggs) == 1
        assert aggs[0].anchor_text == "Valid"
