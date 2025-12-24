"""
Competitive backlink analysis service.

Provides methods for:
- Overlap analysis: Find domains linking to both target and competitors
- Intersect/Gap analysis: Find domains linking to competitors but NOT to target
- New/Lost analysis: Track domains gained/lost between snapshots
"""

import uuid
from typing import Any

from sqlmodel import Session, select

from app.models.links import RefDomainAgg


class CompetitiveAnalyzer:
    """Compute competitive backlink metrics."""

    def __init__(self, session: Session):
        """
        Initialize the CompetitiveAnalyzer.

        Args:
            session: SQLModel database session
        """
        self.session = session

    def compute_overlap(
        self,
        target_domain: str,
        competitor_domains: list[str],
        snapshot_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """
        Find domains that link to both target and competitors.

        This identifies shared referring domains, which can indicate:
        - Industry-relevant sites that link to multiple players
        - Citation sources that acknowledge multiple authorities
        - Potential partnership or networking opportunities

        Args:
            target_domain: The target domain to analyze
            competitor_domains: List of competitor domains
            snapshot_id: The link snapshot ID to query

        Returns:
            List of dicts sorted by total competitor links (descending).
            Each result contains:
            - domain: The referring domain
            - links_to_you: Number of links to target domain
            - links_to_competitors: Dict mapping competitor domains to link counts
        """
        all_domains = [target_domain] + competitor_domains

        # Get ref domains for each target
        domain_refs: dict[str, set[str]] = {}
        for domain in all_domains:
            stmt = (
                select(RefDomainAgg.ref_domain)
                .where(RefDomainAgg.snapshot_id == snapshot_id)
                .where(RefDomainAgg.target_domain == domain)
            )
            domain_refs[domain] = set(self.session.exec(stmt))

        # Find intersection - domains linking to target AND at least one competitor
        target_refs = domain_refs.get(target_domain, set())
        competitor_refs = set()
        for comp in competitor_domains:
            competitor_refs.update(domain_refs.get(comp, set()))

        shared = target_refs & competitor_refs

        # Build detailed overlap data
        results = []
        for ref_domain in shared:
            # Get link counts for each target
            links_to: dict[str, int] = {}
            for domain in all_domains:
                count_stmt = (
                    select(RefDomainAgg.backlinks_count)
                    .where(RefDomainAgg.snapshot_id == snapshot_id)
                    .where(RefDomainAgg.target_domain == domain)
                    .where(RefDomainAgg.ref_domain == ref_domain)
                )
                count = self.session.exec(count_stmt).first()
                if count is not None:
                    links_to[domain] = count

            results.append({
                "domain": ref_domain,
                "links_to_you": links_to.get(target_domain, 0),
                "links_to_competitors": {
                    d: links_to.get(d, 0) for d in competitor_domains
                },
            })

        # Sort by total competitor links (descending)
        results.sort(
            key=lambda x: sum(x["links_to_competitors"].values()),  # type: ignore[attr-defined]
            reverse=True,
        )

        return results

    def compute_intersect(
        self,
        target_domain: str,
        competitor_domains: list[str],
        snapshot_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """
        Find domains that link to competitors but NOT to target.

        These are link building opportunities - sites that already link
        to similar/competing content but haven't linked to the target yet.

        Args:
            target_domain: The target domain to analyze
            competitor_domains: List of competitor domains
            snapshot_id: The link snapshot ID to query

        Returns:
            List of dicts sorted by (competitor_count, total_links) descending.
            Each result contains:
            - domain: The referring domain
            - links_to_competitors: Dict mapping competitor domains to link counts
            - competitor_count: Number of competitors this domain links to
            - total_links: Total number of links to all competitors
        """
        # Get target's ref domains
        target_stmt = (
            select(RefDomainAgg.ref_domain)
            .where(RefDomainAgg.snapshot_id == snapshot_id)
            .where(RefDomainAgg.target_domain == target_domain)
        )
        target_refs = set(self.session.exec(target_stmt))

        # Get competitor ref domains
        competitor_refs: dict[str, set[str]] = {}
        for comp in competitor_domains:
            stmt = (
                select(RefDomainAgg.ref_domain)
                .where(RefDomainAgg.snapshot_id == snapshot_id)
                .where(RefDomainAgg.target_domain == comp)
            )
            competitor_refs[comp] = set(self.session.exec(stmt))

        # Find domains linking to competitors but not target
        all_competitor_refs = set()
        for refs in competitor_refs.values():
            all_competitor_refs.update(refs)

        gap_domains = all_competitor_refs - target_refs

        # Build results with competitor link counts
        results = []
        for ref_domain in gap_domains:
            links_to: dict[str, int] = {}
            for comp in competitor_domains:
                if ref_domain in competitor_refs.get(comp, set()):
                    count_stmt = (
                        select(RefDomainAgg.backlinks_count)
                        .where(RefDomainAgg.snapshot_id == snapshot_id)
                        .where(RefDomainAgg.target_domain == comp)
                        .where(RefDomainAgg.ref_domain == ref_domain)
                    )
                    count = self.session.exec(count_stmt).first()
                    if count is not None:
                        links_to[comp] = count

            # Only include if links to at least one competitor
            if len(links_to) >= 1:
                results.append({
                    "domain": ref_domain,
                    "links_to_competitors": links_to,
                    "competitor_count": len(links_to),
                    "total_links": sum(links_to.values()),
                })

        # Sort by number of competitors linking, then total links
        results.sort(
            key=lambda x: (x["competitor_count"], x["total_links"]),
            reverse=True,
        )

        return results

    def compute_new_lost(
        self,
        target_domain: str,
        current_snapshot_id: uuid.UUID,
        previous_snapshot_id: uuid.UUID,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Find new and lost referring domains between snapshots.

        Tracks which domains have started linking (new) or stopped linking (lost)
        to the target domain between two snapshots.

        Args:
            target_domain: The target domain to analyze
            current_snapshot_id: The current/latest snapshot ID
            previous_snapshot_id: The previous snapshot ID to compare against

        Returns:
            Dict with two keys:
            - new: List of domains that are new in current snapshot
            - lost: List of domains that disappeared from current snapshot

            Each domain dict contains:
            - domain: The referring domain
            - backlinks_count: Number of backlinks
            - first_seen: (for new) First seen timestamp
            - last_seen: (for lost) Last seen timestamp
        """
        # Get ref domains from both snapshots
        def get_refs(snapshot_id: uuid.UUID) -> dict[str, dict[str, Any]]:
            stmt = (
                select(RefDomainAgg)
                .where(RefDomainAgg.snapshot_id == snapshot_id)
                .where(RefDomainAgg.target_domain == target_domain)
            )
            return {
                r.ref_domain: {
                    "backlinks_count": r.backlinks_count,
                    "first_seen": r.first_seen,
                    "last_seen": r.last_seen,
                }
                for r in self.session.exec(stmt)
            }

        current = get_refs(current_snapshot_id)
        previous = get_refs(previous_snapshot_id)

        current_domains = set(current.keys())
        previous_domains = set(previous.keys())

        new_domains = current_domains - previous_domains
        lost_domains = previous_domains - current_domains

        return {
            "new": [
                {
                    "domain": d,
                    "backlinks_count": current[d]["backlinks_count"],
                    "first_seen": current[d]["first_seen"],
                }
                for d in new_domains
            ],
            "lost": [
                {
                    "domain": d,
                    "backlinks_count": previous[d]["backlinks_count"],
                    "last_seen": previous[d]["last_seen"],
                }
                for d in lost_domains
            ],
        }
