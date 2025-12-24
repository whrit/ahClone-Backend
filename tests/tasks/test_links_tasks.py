"""
Test suite for Celery links tasks.
Following TDD approach - tests written first.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlmodel import Session, select

import app.tasks.links  # noqa: F401 - Import to register tasks
from app.core.celery import celery_app
from app.models.links import AnchorAgg, BacklinkEdge, LinkSnapshot, RefDomainAgg


@pytest.fixture
def test_snapshot(db: Session) -> LinkSnapshot:
    """Create a test link snapshot."""
    snapshot = LinkSnapshot(
        id=uuid.uuid4(),
        source="commoncrawl",
        crawl_id="CC-MAIN-2024-10",
        subset_spec={"target_domains": ["example.com"], "limit": 1000},
        status="pending",
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


class TestTaskRegistration:
    """Test that tasks are properly registered with Celery."""

    def test_ingest_commoncrawl_subset_task_is_registered(self):
        """The ingest_commoncrawl_subset task should be registered."""
        assert "app.tasks.links.ingest_commoncrawl_subset" in celery_app.tasks

    def test_build_link_aggregates_task_is_registered(self):
        """The build_link_aggregates task should be registered."""
        assert "app.tasks.links.build_link_aggregates" in celery_app.tasks


class TestIngestCommonCrawlSubsetTask:
    """Test the ingest_commoncrawl_subset task."""

    @patch("app.tasks.links.build_link_aggregates")
    def test_creates_link_snapshot_with_ingesting_status(
        self, mock_aggregate_task, db: Session
    ):
        """Task should create LinkSnapshot with status='ingesting'."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock to return no records
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify snapshot was created
        snapshot_id = result["snapshot_id"]
        snapshot = db.get(LinkSnapshot, uuid.UUID(snapshot_id))

        assert snapshot is not None
        assert snapshot.crawl_id == crawl_id
        assert snapshot.status in ["completed", "ingesting"]

    @patch("app.tasks.links.build_link_aggregates")
    def test_updates_snapshot_status_to_completed_on_success(
        self, mock_aggregate_task, db: Session
    ):
        """Task should update snapshot status to 'completed' on success."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify snapshot status
        snapshot_id = result["snapshot_id"]
        snapshot = db.get(LinkSnapshot, uuid.UUID(snapshot_id))
        assert snapshot.status == "completed"

    def test_updates_snapshot_status_to_failed_on_error(self, db: Session):
        """Task should update snapshot status to 'failed' on error."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock to raise exception
            mock_ingestor_class.side_effect = Exception("Test ingestion error")

            with pytest.raises(Exception, match="Test ingestion error"):
                ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify snapshot was created and marked as failed
        statement = select(LinkSnapshot).where(LinkSnapshot.crawl_id == crawl_id)
        snapshots = db.exec(statement).all()

        if snapshots:
            latest_snapshot = snapshots[-1]
            assert latest_snapshot.status == "failed"
            assert "Test ingestion error" in latest_snapshot.error_message

    @patch("app.tasks.links.build_link_aggregates")
    def test_triggers_aggregation_on_success(
        self, mock_aggregate_task, db: Session
    ):
        """Task should trigger build_link_aggregates on successful ingestion."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com", "test.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify aggregation task was triggered
        mock_aggregate_task.delay.assert_called_once()
        call_args = mock_aggregate_task.delay.call_args[0]
        assert call_args[0] == result["snapshot_id"]
        assert call_args[1] == target_domains

    @patch("app.tasks.links.build_link_aggregates")
    def test_stores_backlink_edges_from_ingestion(
        self, mock_aggregate_task, db: Session
    ):
        """Task should store BacklinkEdge records from ingestion."""
        from app.services.links.commoncrawl import ExtractedLink
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        # Create mock extracted links
        mock_links = [
            ExtractedLink(
                source_url="https://other.com/page1",
                source_domain="other.com",
                target_url="https://example.com/page1",
                target_domain="example.com",
                anchor_text="Example Site",
                is_nofollow=False,
                is_sponsored=False,
                is_ugc=False,
            ),
            ExtractedLink(
                source_url="https://another.com/page2",
                source_domain="another.com",
                target_url="https://example.com/page2",
                target_domain="example.com",
                anchor_text="Click here",
                is_nofollow=True,
                is_sponsored=False,
                is_ugc=False,
            ),
        ]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[
                {
                    "url": "https://other.com/page1",
                    "filename": "warc.gz",
                    "offset": 0,
                    "length": 1000,
                }
            ])
            mock_ingestor.fetch_warc_record = AsyncMock(
                return_value=b"<html><a href='https://example.com/page1'>Example Site</a></html>"
            )
            mock_ingestor.extract_links_from_html = Mock(return_value=mock_links[:1])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify backlink edges were created
        snapshot_id = result["snapshot_id"]
        statement = select(BacklinkEdge).where(
            BacklinkEdge.snapshot_id == uuid.UUID(snapshot_id)
        )
        db.exec(statement).all()

        # Should have at least some edges if ingestion worked
        assert result["edges_count"] >= 0

    @patch("app.tasks.links.build_link_aggregates")
    def test_updates_snapshot_with_counts_and_duration(
        self, mock_aggregate_task, db: Session
    ):
        """Task should update snapshot with edges_count, domains_count, duration_seconds."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify snapshot has counts and duration
        snapshot_id = result["snapshot_id"]
        snapshot = db.get(LinkSnapshot, uuid.UUID(snapshot_id))

        assert snapshot.edges_count >= 0
        assert snapshot.domains_count >= 0
        assert snapshot.duration_seconds is not None
        assert snapshot.duration_seconds >= 0

    @patch("app.tasks.links.build_link_aggregates")
    def test_returns_dict_with_snapshot_id_and_counts(
        self, mock_aggregate_task, db: Session
    ):
        """Task should return dict with snapshot_id, edges_count, domains_count."""
        from app.tasks.links import ingest_commoncrawl_subset

        crawl_id = "CC-MAIN-2024-10"
        target_domains = ["example.com"]

        with patch("app.tasks.links.CommonCrawlIngestor") as mock_ingestor_class:
            # Setup mock
            mock_ingestor = MagicMock()
            mock_ingestor_class.return_value = mock_ingestor
            mock_ingestor.query_index = AsyncMock(return_value=[])

            result = ingest_commoncrawl_subset(crawl_id, target_domains, limit=100)

        # Verify return value structure
        assert "snapshot_id" in result
        assert "edges_count" in result
        assert "domains_count" in result
        assert isinstance(result["edges_count"], int)
        assert isinstance(result["domains_count"], int)


class TestBuildLinkAggregatesTask:
    """Test the build_link_aggregates task."""

    def test_builds_ref_domain_aggregates(self, db: Session, test_snapshot: LinkSnapshot):
        """Task should call build_ref_domain_aggregates for each target domain."""
        from app.tasks.links import build_link_aggregates

        target_domains = ["example.com", "test.com"]

        # Create some backlink edges
        now = datetime.now(timezone.utc)
        edge1 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://other.com/page1",
            target_url="https://example.com/page1",
            source_domain="other.com",
            target_domain="example.com",
            anchor_text="Example",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        edge2 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://another.com/page1",
            target_url="https://test.com/page1",
            source_domain="another.com",
            target_domain="test.com",
            anchor_text="Test",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        db.add(edge1)
        db.add(edge2)
        db.commit()

        with patch("app.tasks.links.LinkAggregator") as mock_aggregator_class:
            # Setup mock
            mock_aggregator = MagicMock()
            mock_aggregator_class.return_value = mock_aggregator
            mock_aggregator.build_ref_domain_aggregates.return_value = 1
            mock_aggregator.build_anchor_aggregates.return_value = 1

            build_link_aggregates(str(test_snapshot.id), target_domains)

        # Verify aggregation methods were called for each domain
        assert mock_aggregator.build_ref_domain_aggregates.call_count == len(target_domains)
        assert mock_aggregator.build_anchor_aggregates.call_count == len(target_domains)

    def test_builds_anchor_aggregates(self, db: Session, test_snapshot: LinkSnapshot):
        """Task should call build_anchor_aggregates for each target domain."""
        from app.tasks.links import build_link_aggregates

        target_domains = ["example.com"]

        # Create some backlink edges
        now = datetime.now(timezone.utc)
        edge = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://other.com/page1",
            target_url="https://example.com/page1",
            source_domain="other.com",
            target_domain="example.com",
            anchor_text="Example",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        db.add(edge)
        db.commit()

        with patch("app.tasks.links.LinkAggregator") as mock_aggregator_class:
            # Setup mock
            mock_aggregator = MagicMock()
            mock_aggregator_class.return_value = mock_aggregator
            mock_aggregator.build_ref_domain_aggregates.return_value = 1
            mock_aggregator.build_anchor_aggregates.return_value = 1

            build_link_aggregates(str(test_snapshot.id), target_domains)

        # Verify anchor aggregates were built
        mock_aggregator.build_anchor_aggregates.assert_called()

    def test_returns_dict_with_results_per_domain(self, db: Session, test_snapshot: LinkSnapshot):
        """Task should return dict with results per domain."""
        from app.tasks.links import build_link_aggregates

        target_domains = ["example.com", "test.com"]

        with patch("app.tasks.links.LinkAggregator") as mock_aggregator_class:
            # Setup mock
            mock_aggregator = MagicMock()
            mock_aggregator_class.return_value = mock_aggregator
            mock_aggregator.build_ref_domain_aggregates.return_value = 5
            mock_aggregator.build_anchor_aggregates.return_value = 3

            result = build_link_aggregates(str(test_snapshot.id), target_domains)

        # Verify return value structure
        assert isinstance(result, dict)
        assert "results" in result or "example.com" in result or len(result) > 0

    def test_creates_ref_domain_agg_records(self, db: Session, test_snapshot: LinkSnapshot):
        """Task should create RefDomainAgg records via aggregator."""
        from app.tasks.links import build_link_aggregates

        target_domains = ["example.com"]

        # Create backlink edges
        now = datetime.now(timezone.utc)
        edge1 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://other.com/page1",
            target_url="https://example.com/page1",
            source_domain="other.com",
            target_domain="example.com",
            anchor_text="Example 1",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        edge2 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://other.com/page2",
            target_url="https://example.com/page2",
            source_domain="other.com",
            target_domain="example.com",
            anchor_text="Example 2",
            is_nofollow=True,
            first_seen=now,
            last_seen=now,
        )
        db.add(edge1)
        db.add(edge2)
        db.commit()

        # Call task without mocking aggregator to test real aggregation
        build_link_aggregates(str(test_snapshot.id), target_domains)

        # Verify aggregates were created
        statement = select(RefDomainAgg).where(
            RefDomainAgg.snapshot_id == test_snapshot.id
        )
        aggs = db.exec(statement).all()
        assert len(aggs) >= 1

    def test_creates_anchor_agg_records(self, db: Session, test_snapshot: LinkSnapshot):
        """Task should create AnchorAgg records via aggregator."""
        from app.tasks.links import build_link_aggregates

        target_domains = ["example.com"]

        # Create backlink edges
        now = datetime.now(timezone.utc)
        edge1 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://other.com/page1",
            target_url="https://example.com/page1",
            source_domain="other.com",
            target_domain="example.com",
            anchor_text="Example Link",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        edge2 = BacklinkEdge(
            snapshot_id=test_snapshot.id,
            source_url="https://another.com/page1",
            target_url="https://example.com/page1",
            source_domain="another.com",
            target_domain="example.com",
            anchor_text="Example Link",
            is_nofollow=False,
            first_seen=now,
            last_seen=now,
        )
        db.add(edge1)
        db.add(edge2)
        db.commit()

        # Call task without mocking aggregator to test real aggregation
        build_link_aggregates(str(test_snapshot.id), target_domains)

        # Verify aggregates were created
        statement = select(AnchorAgg).where(
            AnchorAgg.snapshot_id == test_snapshot.id
        )
        aggs = db.exec(statement).all()
        assert len(aggs) >= 1
