"""
Celery tasks for backlinks workflow.

This module implements the backlink ingestion pipeline:
1. ingest_commoncrawl_subset: Ingest backlink data from CommonCrawl
2. build_link_aggregates: Build referring domain and anchor aggregations
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from sqlmodel import Session

from app.core.db import engine
from app.models.links import BacklinkEdge, LinkSnapshot
from app.services.links.aggregator import LinkAggregator
from app.services.links.commoncrawl import CommonCrawlIngestor


@shared_task(name="app.tasks.links.ingest_commoncrawl_subset")  # type: ignore[misc]
def ingest_commoncrawl_subset(
    crawl_id: str, target_domains: list[str], limit: int = 50000
) -> dict[str, Any]:
    """
    Ingest backlink data from CommonCrawl for specified target domains.

    This task:
    1. Creates a LinkSnapshot record with status="ingesting"
    2. Initializes CommonCrawlIngestor
    3. Queries CommonCrawl index for pages linking to target domains
    4. Fetches WARC records and extracts links
    5. Stores BacklinkEdge records
    6. Updates snapshot with counts and duration
    7. Triggers build_link_aggregates on success

    Args:
        crawl_id: CommonCrawl dataset ID (e.g., "CC-MAIN-2024-10")
        target_domains: List of domains to find backlinks for
        limit: Maximum number of WARC records to process (default: 50000)

    Returns:
        Dict with snapshot_id, edges_count, domains_count

    Raises:
        Exception: On ingestion failure (snapshot marked as failed)
    """
    snapshot_id: uuid.UUID | None = None
    start_time = datetime.now(timezone.utc)

    with Session(engine) as session:
        try:
            # Create LinkSnapshot with status="ingesting"
            snapshot = LinkSnapshot(
                id=uuid.uuid4(),
                source="commoncrawl",
                crawl_id=crawl_id,
                subset_spec={
                    "target_domains": target_domains,
                    "limit": limit,
                },
                status="ingesting",
                ingested_at=start_time,
            )
            session.add(snapshot)
            session.commit()
            session.refresh(snapshot)
            snapshot_id = snapshot.id

            # Initialize CommonCrawlIngestor
            ingestor = CommonCrawlIngestor()

            # Track statistics
            edges_count = 0
            source_domains_set: set[str] = set()

            async def run_ingestion() -> None:
                nonlocal edges_count, source_domains_set

                # Query CommonCrawl index for each target domain
                for target_domain in target_domains:
                    # Query index for pages linking to this domain
                    # Use wildcard pattern to find all pages on the domain
                    url_pattern = f"*.{target_domain}/*"
                    try:
                        index_records = await ingestor.query_index(
                            crawl_id=crawl_id,
                            url_pattern=url_pattern,
                            limit=limit,
                        )
                    except Exception:
                        # If query fails, continue with next domain
                        continue

                    # Process each WARC record
                    for record in index_records[:limit]:
                        try:
                            # Fetch WARC record
                            warc_content = await ingestor.fetch_warc_record(
                                warc_filename=record.get("filename", ""),
                                offset=record.get("offset", 0),
                                length=record.get("length", 0),
                            )

                            # Extract HTML from WARC (simplified - just decode)
                            html = warc_content.decode("utf-8", errors="ignore")
                            source_url = record.get("url", "")

                            # Extract links from HTML
                            for link in ingestor.extract_links_from_html(
                                html=html, source_url=source_url
                            ):
                                # Only store links to target domains
                                if link.target_domain not in target_domains:
                                    continue

                                # Create BacklinkEdge record
                                now = datetime.now(timezone.utc)
                                edge = BacklinkEdge(
                                    snapshot_id=snapshot.id,
                                    source_url=link.source_url,
                                    target_url=link.target_url,
                                    source_domain=link.source_domain,
                                    target_domain=link.target_domain,
                                    anchor_text=link.anchor_text,
                                    is_nofollow=link.is_nofollow,
                                    is_sponsored=link.is_sponsored,
                                    is_ugc=link.is_ugc,
                                    first_seen=now,
                                    last_seen=now,
                                )
                                session.add(edge)
                                edges_count += 1
                                source_domains_set.add(link.source_domain)

                                # Commit in batches
                                if edges_count % 100 == 0:
                                    session.commit()

                        except Exception:
                            # Skip failed WARC records
                            continue

                # Final commit
                session.commit()

            # Run the ingestion
            asyncio.run(run_ingestion())

            # Calculate duration
            end_time = datetime.now(timezone.utc)
            duration_seconds = int((end_time - start_time).total_seconds())

            # Update snapshot with counts and duration
            snapshot.edges_count = edges_count
            snapshot.domains_count = len(source_domains_set)
            snapshot.duration_seconds = duration_seconds
            snapshot.status = "completed"
            session.add(snapshot)
            session.commit()

            # Trigger aggregation task
            build_link_aggregates.delay(str(snapshot_id), target_domains)

            return {
                "snapshot_id": str(snapshot_id),
                "edges_count": edges_count,
                "domains_count": len(source_domains_set),
            }

        except Exception as e:
            # Update snapshot status to failed
            if snapshot_id:
                snapshot_to_update = session.get(LinkSnapshot, snapshot_id)
                if snapshot_to_update:
                    snapshot_to_update.status = "failed"
                    snapshot_to_update.error_message = str(e)[:2000]

                    # Calculate duration even on failure
                    end_time = datetime.now(timezone.utc)
                    duration_seconds = int((end_time - start_time).total_seconds())
                    snapshot_to_update.duration_seconds = duration_seconds

                    session.add(snapshot_to_update)
                    session.commit()
            raise


@shared_task(name="app.tasks.links.build_link_aggregates")  # type: ignore[misc]
def build_link_aggregates(
    snapshot_id: str, target_domains: list[str]
) -> dict[str, Any]:
    """
    Build referring domain and anchor text aggregations for a snapshot.

    This task:
    1. Initializes LinkAggregator with database session
    2. For each target domain:
       - Calls build_ref_domain_aggregates()
       - Calls build_anchor_aggregates()
    3. Returns aggregation results per domain

    Args:
        snapshot_id: UUID of the LinkSnapshot to aggregate
        target_domains: List of domains to build aggregates for

    Returns:
        Dict with aggregation results per domain
    """
    with Session(engine) as session:
        # Initialize aggregator
        aggregator = LinkAggregator(session=session)

        # Build aggregates for each target domain
        results: dict[str, dict[str, int]] = {}

        for target_domain in target_domains:
            # Build referring domain aggregates
            ref_domain_count = aggregator.build_ref_domain_aggregates(
                snapshot_id=uuid.UUID(snapshot_id),
                target_domain=target_domain,
            )

            # Build anchor text aggregates
            anchor_count = aggregator.build_anchor_aggregates(
                snapshot_id=uuid.UUID(snapshot_id),
                target_domain=target_domain,
            )

            # Store results
            results[target_domain] = {
                "ref_domains": ref_domain_count,
                "anchors": anchor_count,
            }

        return results
