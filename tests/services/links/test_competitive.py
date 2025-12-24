"""
Test suite for Competitive Analysis Service.
Following TDD approach - tests written first.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlmodel import Session

from app.models.links import LinkSnapshot, RefDomainAgg
from app.services.links.competitive import CompetitiveAnalyzer


@pytest.fixture
def link_snapshot(db: Session) -> LinkSnapshot:
    """Create a test link snapshot."""
    snapshot = LinkSnapshot(
        id=uuid.uuid4(),
        source="commoncrawl",
        crawl_id="CC-MAIN-2024-10",
        subset_spec={"test": "data"},
        status="completed",
        edges_count=100,
        domains_count=10,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@pytest.fixture
def previous_snapshot(db: Session) -> LinkSnapshot:
    """Create a previous test link snapshot for new/lost analysis."""
    snapshot = LinkSnapshot(
        id=uuid.uuid4(),
        source="commoncrawl",
        crawl_id="CC-MAIN-2024-09",
        subset_spec={"test": "data"},
        status="completed",
        edges_count=80,
        domains_count=8,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@pytest.fixture
def ref_domain_data(db: Session, link_snapshot: LinkSnapshot) -> dict[str, str]:
    """
    Create comprehensive RefDomainAgg test data for competitive analysis.

    Setup:
    - Target domain: example.com
    - Competitor 1: competitor1.com
    - Competitor 2: competitor2.com

    Referring domains:
    - shared1.com: links to ALL (target + both competitors)
    - shared2.com: links to target + competitor1
    - shared3.com: links to both competitors only
    - unique-to-target.com: links only to target
    - unique-to-comp1.com: links only to competitor1
    - unique-to-comp2.com: links only to competitor2
    - opportunity1.com: links to both competitors but NOT target
    - opportunity2.com: links to competitor1 only but NOT target
    """
    now = datetime.now(timezone.utc)

    # Domain linking to all three (target + both competitors)
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="example.com",
        ref_domain="shared1.com",
        backlinks_count=10,
        dofollow_count=8,
        nofollow_count=2,
        first_seen=now,
        last_seen=now,
        top_anchors=["example", "click here"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor1.com",
        ref_domain="shared1.com",
        backlinks_count=15,
        dofollow_count=12,
        nofollow_count=3,
        first_seen=now,
        last_seen=now,
        top_anchors=["competitor1"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor2.com",
        ref_domain="shared1.com",
        backlinks_count=8,
        dofollow_count=6,
        nofollow_count=2,
        first_seen=now,
        last_seen=now,
        top_anchors=["competitor2"]
    ))

    # Domain linking to target + competitor1
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="example.com",
        ref_domain="shared2.com",
        backlinks_count=5,
        dofollow_count=5,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["example site"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor1.com",
        ref_domain="shared2.com",
        backlinks_count=7,
        dofollow_count=7,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp1"]
    ))

    # Domain unique to target
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="example.com",
        ref_domain="unique-to-target.com",
        backlinks_count=3,
        dofollow_count=3,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["unique"]
    ))

    # Domain unique to competitor1
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor1.com",
        ref_domain="unique-to-comp1.com",
        backlinks_count=4,
        dofollow_count=4,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp1 unique"]
    ))

    # Domain unique to competitor2
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor2.com",
        ref_domain="unique-to-comp2.com",
        backlinks_count=6,
        dofollow_count=5,
        nofollow_count=1,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp2 unique"]
    ))

    # Opportunity 1: links to both competitors but NOT target
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor1.com",
        ref_domain="opportunity1.com",
        backlinks_count=20,
        dofollow_count=18,
        nofollow_count=2,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp1 opp"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor2.com",
        ref_domain="opportunity1.com",
        backlinks_count=12,
        dofollow_count=10,
        nofollow_count=2,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp2 opp"]
    ))

    # Opportunity 2: links to competitor1 only but NOT target
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain="competitor1.com",
        ref_domain="opportunity2.com",
        backlinks_count=9,
        dofollow_count=8,
        nofollow_count=1,
        first_seen=now,
        last_seen=now,
        top_anchors=["comp1 opp2"]
    ))

    db.commit()

    return {
        "target": "example.com",
        "competitor1": "competitor1.com",
        "competitor2": "competitor2.com",
        "shared_all": "shared1.com",
        "shared_target_comp1": "shared2.com",
        "unique_target": "unique-to-target.com",
        "unique_comp1": "unique-to-comp1.com",
        "unique_comp2": "unique-to-comp2.com",
        "opportunity1": "opportunity1.com",
        "opportunity2": "opportunity2.com",
    }


@pytest.fixture
def new_lost_data(db: Session, link_snapshot: LinkSnapshot, previous_snapshot: LinkSnapshot) -> dict[str, Any]:
    """
    Create test data for new/lost analysis.

    Previous snapshot domains: domain1.com, domain2.com, domain3.com
    Current snapshot domains: domain2.com, domain3.com, domain4.com

    New: domain4.com
    Lost: domain1.com
    Retained: domain2.com, domain3.com
    """
    now = datetime.now(timezone.utc)
    target = "example.com"

    # Previous snapshot data
    db.add(RefDomainAgg(
        snapshot_id=previous_snapshot.id,
        target_domain=target,
        ref_domain="domain1.com",
        backlinks_count=5,
        dofollow_count=5,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["old"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=previous_snapshot.id,
        target_domain=target,
        ref_domain="domain2.com",
        backlinks_count=8,
        dofollow_count=7,
        nofollow_count=1,
        first_seen=now,
        last_seen=now,
        top_anchors=["retained"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=previous_snapshot.id,
        target_domain=target,
        ref_domain="domain3.com",
        backlinks_count=3,
        dofollow_count=3,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["also retained"]
    ))

    # Current snapshot data
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain=target,
        ref_domain="domain2.com",
        backlinks_count=10,
        dofollow_count=9,
        nofollow_count=1,
        first_seen=now,
        last_seen=now,
        top_anchors=["retained"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain=target,
        ref_domain="domain3.com",
        backlinks_count=4,
        dofollow_count=4,
        nofollow_count=0,
        first_seen=now,
        last_seen=now,
        top_anchors=["also retained"]
    ))
    db.add(RefDomainAgg(
        snapshot_id=link_snapshot.id,
        target_domain=target,
        ref_domain="domain4.com",
        backlinks_count=12,
        dofollow_count=10,
        nofollow_count=2,
        first_seen=now,
        last_seen=now,
        top_anchors=["new"]
    ))

    db.commit()

    return {
        "target": target,
        "new_domains": ["domain4.com"],
        "lost_domains": ["domain1.com"],
        "retained_domains": ["domain2.com", "domain3.com"],
    }


class TestCompetitiveAnalyzer:
    """Test CompetitiveAnalyzer service."""

    def test_analyzer_initialization(self, db: Session) -> None:
        """CompetitiveAnalyzer should initialize with a session."""
        analyzer = CompetitiveAnalyzer(db)
        assert analyzer.session == db

    def test_compute_overlap_finds_shared_domains(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_overlap should find domains linking to both target and competitors."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_overlap(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        # Should find shared1.com and shared2.com
        assert len(results) == 2

        # Results should be sorted by total competitor links (descending)
        # shared1.com has 15 + 8 = 23 competitor links
        # shared2.com has 7 + 0 = 7 competitor links
        assert results[0]["domain"] == "shared1.com"
        assert results[1]["domain"] == "shared2.com"

    def test_compute_overlap_returns_correct_structure(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_overlap should return correct data structure for each domain."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_overlap(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        # Check shared1.com (links to all three)
        shared1_result = next(r for r in results if r["domain"] == "shared1.com")
        assert shared1_result["links_to_you"] == 10
        assert shared1_result["links_to_competitors"][ref_domain_data["competitor1"]] == 15
        assert shared1_result["links_to_competitors"][ref_domain_data["competitor2"]] == 8

    def test_compute_overlap_excludes_unique_domains(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_overlap should NOT include domains linking only to target or only to competitors."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_overlap(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        result_domains = [r["domain"] for r in results]

        # Should NOT include domains linking only to target
        assert ref_domain_data["unique_target"] not in result_domains

        # Should NOT include domains linking only to competitors
        assert ref_domain_data["opportunity1"] not in result_domains
        assert ref_domain_data["opportunity2"] not in result_domains

    def test_compute_overlap_with_single_competitor(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_overlap should work with a single competitor."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_overlap(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"]],
            snapshot_id=link_snapshot.id
        )

        # Should find shared1.com and shared2.com
        assert len(results) == 2
        result_domains = [r["domain"] for r in results]
        assert "shared1.com" in result_domains
        assert "shared2.com" in result_domains

    def test_compute_overlap_with_no_overlap(
        self, db: Session, link_snapshot: LinkSnapshot
    ) -> None:
        """compute_overlap should return empty list when no overlap exists."""
        analyzer = CompetitiveAnalyzer(db)

        # Create data with no overlap
        now = datetime.now(timezone.utc)
        db.add(RefDomainAgg(
            snapshot_id=link_snapshot.id,
            target_domain="nooverlap-target.com",
            ref_domain="unique1.com",
            backlinks_count=5,
            dofollow_count=5,
            nofollow_count=0,
            first_seen=now,
            last_seen=now,
            top_anchors=[]
        ))
        db.add(RefDomainAgg(
            snapshot_id=link_snapshot.id,
            target_domain="nooverlap-comp.com",
            ref_domain="unique2.com",
            backlinks_count=5,
            dofollow_count=5,
            nofollow_count=0,
            first_seen=now,
            last_seen=now,
            top_anchors=[]
        ))
        db.commit()

        results = analyzer.compute_overlap(
            target_domain="nooverlap-target.com",
            competitor_domains=["nooverlap-comp.com"],
            snapshot_id=link_snapshot.id
        )

        assert len(results) == 0

    def test_compute_intersect_finds_gap_opportunities(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_intersect should find domains linking to competitors but NOT to target."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_intersect(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        # Should find opportunity1.com, opportunity2.com, unique-to-comp1.com, unique-to-comp2.com
        assert len(results) == 4

        result_domains = [r["domain"] for r in results]
        assert "opportunity1.com" in result_domains
        assert "opportunity2.com" in result_domains
        assert "unique-to-comp1.com" in result_domains
        assert "unique-to-comp2.com" in result_domains

    def test_compute_intersect_sorted_by_competitor_count_and_links(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_intersect should sort by (competitor_count, total_links) descending."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_intersect(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        # opportunity1.com links to 2 competitors (20 + 12 = 32 total)
        # Others link to 1 competitor each
        assert results[0]["domain"] == "opportunity1.com"
        assert results[0]["competitor_count"] == 2
        assert results[0]["total_links"] == 32

        # Among domains linking to 1 competitor, sort by total_links
        # opportunity2.com: 9 links to competitor1
        # unique-to-comp2.com: 6 links to competitor2
        # unique-to-comp1.com: 4 links to competitor1
        single_comp_results = [r for r in results if r["competitor_count"] == 1]
        assert single_comp_results[0]["domain"] == "opportunity2.com"
        assert single_comp_results[0]["total_links"] == 9

    def test_compute_intersect_returns_correct_structure(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_intersect should return correct data structure."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_intersect(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        # Check opportunity1.com
        opp1_result = next(r for r in results if r["domain"] == "opportunity1.com")
        assert opp1_result["links_to_competitors"][ref_domain_data["competitor1"]] == 20
        assert opp1_result["links_to_competitors"][ref_domain_data["competitor2"]] == 12
        assert opp1_result["competitor_count"] == 2
        assert opp1_result["total_links"] == 32

    def test_compute_intersect_excludes_target_domains(
        self, db: Session, link_snapshot: LinkSnapshot, ref_domain_data: dict[str, str]
    ) -> None:
        """compute_intersect should NOT include domains that also link to target."""
        analyzer = CompetitiveAnalyzer(db)

        results = analyzer.compute_intersect(
            target_domain=ref_domain_data["target"],
            competitor_domains=[ref_domain_data["competitor1"], ref_domain_data["competitor2"]],
            snapshot_id=link_snapshot.id
        )

        result_domains = [r["domain"] for r in results]

        # Should NOT include domains that link to target
        assert "shared1.com" not in result_domains
        assert "shared2.com" not in result_domains
        assert "unique-to-target.com" not in result_domains

    def test_compute_intersect_with_no_gaps(
        self, db: Session, link_snapshot: LinkSnapshot
    ) -> None:
        """compute_intersect should return empty list when target already has all competitor links."""
        analyzer = CompetitiveAnalyzer(db)

        # Create data where target has all the same ref domains as competitor
        now = datetime.now(timezone.utc)
        for ref_domain in ["shared1.com", "shared2.com"]:
            db.add(RefDomainAgg(
                snapshot_id=link_snapshot.id,
                target_domain="complete-target.com",
                ref_domain=ref_domain,
                backlinks_count=5,
                dofollow_count=5,
                nofollow_count=0,
                first_seen=now,
                last_seen=now,
                top_anchors=[]
            ))
            db.add(RefDomainAgg(
                snapshot_id=link_snapshot.id,
                target_domain="complete-comp.com",
                ref_domain=ref_domain,
                backlinks_count=5,
                dofollow_count=5,
                nofollow_count=0,
                first_seen=now,
                last_seen=now,
                top_anchors=[]
            ))
        db.commit()

        results = analyzer.compute_intersect(
            target_domain="complete-target.com",
            competitor_domains=["complete-comp.com"],
            snapshot_id=link_snapshot.id
        )

        assert len(results) == 0

    def test_compute_new_lost_identifies_new_domains(
        self, db: Session, link_snapshot: LinkSnapshot, previous_snapshot: LinkSnapshot, new_lost_data: dict[str, Any]
    ) -> None:
        """compute_new_lost should identify domains that are new in current snapshot."""
        analyzer = CompetitiveAnalyzer(db)

        result = analyzer.compute_new_lost(
            target_domain=new_lost_data["target"],
            current_snapshot_id=link_snapshot.id,
            previous_snapshot_id=previous_snapshot.id
        )

        assert "new" in result
        assert len(result["new"]) == 1
        assert result["new"][0]["domain"] == "domain4.com"
        assert result["new"][0]["backlinks_count"] == 12
        assert result["new"][0]["first_seen"] is not None

    def test_compute_new_lost_identifies_lost_domains(
        self, db: Session, link_snapshot: LinkSnapshot, previous_snapshot: LinkSnapshot, new_lost_data: dict[str, Any]
    ) -> None:
        """compute_new_lost should identify domains that disappeared from current snapshot."""
        analyzer = CompetitiveAnalyzer(db)

        result = analyzer.compute_new_lost(
            target_domain=new_lost_data["target"],
            current_snapshot_id=link_snapshot.id,
            previous_snapshot_id=previous_snapshot.id
        )

        assert "lost" in result
        assert len(result["lost"]) == 1
        assert result["lost"][0]["domain"] == "domain1.com"
        assert result["lost"][0]["backlinks_count"] == 5
        assert result["lost"][0]["last_seen"] is not None

    def test_compute_new_lost_returns_correct_structure(
        self, db: Session, link_snapshot: LinkSnapshot, previous_snapshot: LinkSnapshot, new_lost_data: dict[str, Any]
    ) -> None:
        """compute_new_lost should return dict with 'new' and 'lost' lists."""
        analyzer = CompetitiveAnalyzer(db)

        result = analyzer.compute_new_lost(
            target_domain=new_lost_data["target"],
            current_snapshot_id=link_snapshot.id,
            previous_snapshot_id=previous_snapshot.id
        )

        assert isinstance(result, dict)
        assert "new" in result
        assert "lost" in result
        assert isinstance(result["new"], list)
        assert isinstance(result["lost"], list)

        # Check structure of new domain
        if result["new"]:
            new_domain = result["new"][0]
            assert "domain" in new_domain
            assert "backlinks_count" in new_domain
            assert "first_seen" in new_domain

        # Check structure of lost domain
        if result["lost"]:
            lost_domain = result["lost"][0]
            assert "domain" in lost_domain
            assert "backlinks_count" in lost_domain
            assert "last_seen" in lost_domain

    def test_compute_new_lost_with_no_previous_snapshot(
        self, db: Session, link_snapshot: LinkSnapshot
    ) -> None:
        """compute_new_lost should handle case where all current domains are 'new'."""
        analyzer = CompetitiveAnalyzer(db)

        # Create a completely new snapshot with no previous data
        new_snapshot = LinkSnapshot(
            id=uuid.uuid4(),
            source="commoncrawl",
            crawl_id="CC-MAIN-2024-11",
            subset_spec={},
            status="completed"
        )
        db.add(new_snapshot)
        db.commit()
        db.refresh(new_snapshot)

        # Add some data to current snapshot
        now = datetime.now(timezone.utc)
        db.add(RefDomainAgg(
            snapshot_id=link_snapshot.id,
            target_domain="newdomain.com",
            ref_domain="ref1.com",
            backlinks_count=5,
            dofollow_count=5,
            nofollow_count=0,
            first_seen=now,
            last_seen=now,
            top_anchors=[]
        ))
        db.commit()

        result = analyzer.compute_new_lost(
            target_domain="newdomain.com",
            current_snapshot_id=link_snapshot.id,
            previous_snapshot_id=new_snapshot.id
        )

        # All current domains should be "new"
        assert len(result["new"]) == 1
        assert len(result["lost"]) == 0

    def test_compute_new_lost_with_all_lost(
        self, db: Session, link_snapshot: LinkSnapshot, previous_snapshot: LinkSnapshot
    ) -> None:
        """compute_new_lost should handle case where all previous domains are 'lost'."""
        analyzer = CompetitiveAnalyzer(db)

        # Add data only to previous snapshot
        now = datetime.now(timezone.utc)
        db.add(RefDomainAgg(
            snapshot_id=previous_snapshot.id,
            target_domain="declining.com",
            ref_domain="oldref1.com",
            backlinks_count=5,
            dofollow_count=5,
            nofollow_count=0,
            first_seen=now,
            last_seen=now,
            top_anchors=[]
        ))
        db.add(RefDomainAgg(
            snapshot_id=previous_snapshot.id,
            target_domain="declining.com",
            ref_domain="oldref2.com",
            backlinks_count=3,
            dofollow_count=3,
            nofollow_count=0,
            first_seen=now,
            last_seen=now,
            top_anchors=[]
        ))
        db.commit()

        result = analyzer.compute_new_lost(
            target_domain="declining.com",
            current_snapshot_id=link_snapshot.id,
            previous_snapshot_id=previous_snapshot.id
        )

        # All previous domains should be "lost"
        assert len(result["new"]) == 0
        assert len(result["lost"]) == 2
