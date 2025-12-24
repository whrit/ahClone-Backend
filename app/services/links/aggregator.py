"""
Link Aggregation Service - Sprint 4: Backlinks

This service provides aggregation functions to pre-compute referring domain
and anchor text statistics from individual backlink edges.

Aggregations improve query performance by pre-calculating common metrics
instead of computing them on every API request.
"""
import uuid
from collections import Counter

from sqlalchemy import Integer, func
from sqlmodel import Session, select

from app.models.links import AnchorAgg, BacklinkEdge, RefDomainAgg


class LinkAggregator:
    """
    Aggregates backlink data for efficient querying.

    This service processes raw BacklinkEdge records and creates pre-aggregated
    statistics grouped by referring domain and anchor text.
    """

    def __init__(self, session: Session):
        """
        Initialize the aggregator with a database session.

        Args:
            session: SQLModel database session for executing queries
        """
        self.session = session

    def build_ref_domain_aggregates(
        self,
        snapshot_id: uuid.UUID,
        target_domain: str
    ) -> int:
        """
        Build referring domain aggregates for a snapshot and target domain.

        Groups BacklinkEdge records by source_domain and calculates:
        - Total backlinks count
        - Dofollow count (links where is_nofollow=False)
        - Nofollow count (links where is_nofollow=True)
        - First seen timestamp (min of first_seen)
        - Last seen timestamp (max of last_seen)
        - Top 5 anchor texts by frequency

        Args:
            snapshot_id: ID of the backlink snapshot
            target_domain: Domain to aggregate backlinks for

        Returns:
            Number of RefDomainAgg records created
        """
        # Query BacklinkEdge grouped by source_domain
        # Using SQLAlchemy's func for aggregation functions
        query = (
            select(  # type: ignore[call-overload]
                BacklinkEdge.source_domain,
                func.count(BacklinkEdge.id).label("backlinks_count"),  # type: ignore[arg-type]
                func.sum(func.cast(~BacklinkEdge.is_nofollow, Integer)).label("dofollow_count"),  # type: ignore[arg-type]
                func.sum(func.cast(BacklinkEdge.is_nofollow, Integer)).label("nofollow_count"),  # type: ignore[arg-type]
                func.min(BacklinkEdge.first_seen).label("first_seen"),
                func.max(BacklinkEdge.last_seen).label("last_seen"),
            )
            .where(
                BacklinkEdge.snapshot_id == snapshot_id,
                BacklinkEdge.target_domain == target_domain
            )
            .group_by(BacklinkEdge.source_domain)
        )

        results = self.session.exec(query).all()

        count = 0
        for row in results:
            source_domain = row.source_domain
            backlinks_count = row.backlinks_count
            dofollow_count = row.dofollow_count or 0
            nofollow_count = row.nofollow_count or 0
            first_seen = row.first_seen
            last_seen = row.last_seen

            # Get top 5 anchors for this referring domain
            top_anchors = self._get_top_anchors(snapshot_id, source_domain, target_domain, limit=5)

            # Create RefDomainAgg record
            agg = RefDomainAgg(
                snapshot_id=snapshot_id,
                target_domain=target_domain,
                ref_domain=source_domain,
                backlinks_count=backlinks_count,
                dofollow_count=dofollow_count,
                nofollow_count=nofollow_count,
                first_seen=first_seen,
                last_seen=last_seen,
                top_anchors=top_anchors,
            )
            self.session.add(agg)
            count += 1

        self.session.commit()
        return count

    def build_anchor_aggregates(
        self,
        snapshot_id: uuid.UUID,
        target_domain: str
    ) -> int:
        """
        Build anchor text aggregates for a snapshot and target domain.

        Groups BacklinkEdge records by anchor_text and calculates:
        - Total backlinks count
        - Distinct referring domains count

        Skips null and empty string anchor texts.

        Args:
            snapshot_id: ID of the backlink snapshot
            target_domain: Domain to aggregate backlinks for

        Returns:
            Number of AnchorAgg records created
        """
        # Query BacklinkEdge grouped by anchor_text
        # Filter out null and empty anchors
        query = (
            select(
                BacklinkEdge.anchor_text,
                func.count(BacklinkEdge.id).label("backlinks_count"),  # type: ignore[arg-type]
                func.count(func.distinct(BacklinkEdge.source_domain)).label("ref_domains_count"),
            )
            .where(
                BacklinkEdge.snapshot_id == snapshot_id,
                BacklinkEdge.target_domain == target_domain,
                BacklinkEdge.anchor_text.is_not(None),  # type: ignore[union-attr]
                BacklinkEdge.anchor_text != "",
            )
            .group_by(BacklinkEdge.anchor_text)
        )

        results = self.session.exec(query).all()

        count = 0
        for row in results:
            anchor_text = row.anchor_text  # type: ignore[union-attr]
            backlinks_count = row.backlinks_count  # type: ignore[union-attr]
            ref_domains_count = row.ref_domains_count  # type: ignore[union-attr]

            # Create AnchorAgg record
            agg = AnchorAgg(
                snapshot_id=snapshot_id,
                target_domain=target_domain,
                anchor_text=anchor_text,
                backlinks_count=backlinks_count,
                ref_domains_count=ref_domains_count,
            )
            self.session.add(agg)
            count += 1

        self.session.commit()
        return count

    def _get_top_anchors(
        self,
        snapshot_id: uuid.UUID,
        source_domain: str,
        target_domain: str,
        limit: int = 5
    ) -> list[str]:
        """
        Get top N anchor texts by frequency for a specific referring domain.

        Args:
            snapshot_id: ID of the backlink snapshot
            source_domain: The referring domain to get anchors for
            target_domain: The target domain being linked to
            limit: Maximum number of anchors to return (default: 5)

        Returns:
            List of anchor texts sorted by frequency (most common first)
        """
        # Query all anchor texts for this source domain
        query = (
            select(BacklinkEdge.anchor_text)
            .where(
                BacklinkEdge.snapshot_id == snapshot_id,
                BacklinkEdge.source_domain == source_domain,
                BacklinkEdge.target_domain == target_domain,
                BacklinkEdge.anchor_text.is_not(None),  # type: ignore
            )
        )

        anchor_texts = self.session.exec(query).all()

        # Count occurrences and get top N
        counter = Counter(anchor_texts)
        top_anchors = [anchor for anchor, count in counter.most_common(limit) if anchor is not None]

        return top_anchors
