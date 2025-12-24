"""
Common Crawl ingestion service for backlink data.

This module provides two main ingestors for extracting backlink data from Common Crawl:

1. CommonCrawlIngestor: Low-level ingestor for WARC-based extraction
   - Query Common Crawl index for specific URLs
   - Fetch and parse individual WARC records
   - Extract links from HTML with full anchor text and attributes
   - Suitable for targeted backlink discovery for specific domains

2. BacklinkDatasetIngestor: High-level ingestor for pre-processed domain graphs
   - Download Common Crawl hyperlink graph datasets
   - Process domain-to-domain relationship data
   - Stream large datasets efficiently with batch processing
   - Suitable for bulk backlink analysis and domain authority metrics

Usage Example:
    # WARC-based ingestion for targeted backlink discovery
    from app.services.links.commoncrawl import BacklinkDatasetIngestor
    from app.models.links import LinkSnapshot
    from sqlmodel import Session

    async with Session(engine) as session:
        # Create snapshot record
        snapshot = LinkSnapshot(
            crawl_id="CC-MAIN-2024-10",
            status="ingesting"
        )
        session.add(snapshot)
        session.commit()

        # Ingest backlinks from WARC records
        ingestor = BacklinkDatasetIngestor(session=session)
        stats = await ingestor.ingest_warc_backlinks(
            snapshot_id=snapshot.id,
            crawl_id="CC-MAIN-2024-10",
            url_pattern="*.example.com/*",
            max_pages=100
        )
        print(f"Inserted {stats['edges_inserted']} backlinks")

    # Domain graph ingestion for bulk analysis
    async with Session(engine) as session:
        # Create snapshot record
        snapshot = LinkSnapshot(
            crawl_id="cc-main-2025-sep-oct-nov",
            status="ingesting"
        )
        session.add(snapshot)
        session.commit()

        # Download and process domain graph
        ingestor = BacklinkDatasetIngestor(session=session)
        await ingestor.download_domain_graph(
            "cc-main-2025-sep-oct-nov",
            "/tmp/edges.txt.gz"
        )
        await ingestor.download_vertices(
            "cc-main-2025-sep-oct-nov",
            "/tmp/vertices.txt.gz"
        )

        stats = await ingestor.ingest_to_database(
            snapshot_id=snapshot.id,
            edges_path="/tmp/edges.txt.gz",
            vertices_path="/tmp/vertices.txt.gz",
            batch_size=1000
        )
        print(f"Inserted {stats['edges_inserted']} edges from {stats['unique_domains']} domains")
"""

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


@dataclass
class ExtractedLink:
    """Represents a link extracted from HTML."""

    source_url: str
    source_domain: str
    target_url: str
    target_domain: str
    anchor_text: str | None
    is_nofollow: bool
    is_sponsored: bool
    is_ugc: bool


class CommonCrawlIngestor:
    """Ingestor for Common Crawl data to extract backlinks."""

    CC_INDEX_URL = "https://index.commoncrawl.org"
    CC_DATA_URL = "https://data.commoncrawl.org"

    async def get_available_crawls(self) -> list[dict[str, Any]]:
        """
        Get list of available Common Crawl datasets.

        Returns:
            List of available crawl datasets with metadata
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.CC_INDEX_URL}/collinfo.json")
            result: list[dict[str, Any]] = await response.json()
            return result

    async def query_index(
        self, crawl_id: str, url_pattern: str, limit: int = 10000
    ) -> list[dict[str, Any]]:
        """
        Query Common Crawl index for URLs matching pattern.

        Args:
            crawl_id: Common Crawl dataset ID (e.g., "CC-MAIN-2024-10")
            url_pattern: URL pattern to search for (e.g., "example.com/*")
            limit: Maximum number of results to return

        Returns:
            List of matching index records
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.CC_INDEX_URL}/{crawl_id}-index"
            params = {"url": url_pattern, "output": "json"}
            response = await client.get(url, params=params)

            # Parse newline-delimited JSON
            results: list[dict[str, Any]] = []
            for line in response.text.strip().split("\n"):
                if line and len(results) < limit:
                    results.append(json.loads(line))

            return results[:limit]

    async def fetch_warc_record(
        self, warc_filename: str, offset: int, length: int
    ) -> bytes:
        """
        Fetch a WARC record from Common Crawl.

        Args:
            warc_filename: WARC file path in Common Crawl
            offset: Byte offset in the WARC file
            length: Number of bytes to read

        Returns:
            WARC record content as bytes
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.CC_DATA_URL}/{warc_filename}"
            headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
            response = await client.get(url, headers=headers)
            return response.content

    def extract_links_from_html(
        self, html: str, source_url: str
    ) -> Iterator[ExtractedLink]:
        """
        Extract links from HTML content.

        Args:
            html: HTML content to parse
            source_url: URL of the source page

        Yields:
            ExtractedLink objects for each external link found
        """
        soup = BeautifulSoup(html, "lxml")
        source_domain = self._normalize_domain(self._extract_domain(source_url))

        for anchor in soup.find_all("a"):
            href = anchor.get("href")
            if not href or not isinstance(href, str):
                continue

            # Skip non-HTTP(S) links
            if not href.startswith(("http://", "https://")):
                continue

            # Extract and normalize target domain
            target_domain = self._normalize_domain(self._extract_domain(href))

            # Skip internal links (same domain)
            if target_domain == source_domain:
                continue

            # Extract anchor text
            anchor_text_raw = anchor.get_text(strip=True)
            anchor_text: str | None = None
            if anchor_text_raw:
                anchor_text = anchor_text_raw[:500] if len(anchor_text_raw) > 500 else anchor_text_raw

            # Truncate URL if needed
            target_url: str = href[:2048] if len(href) > 2048 else href

            # Parse rel attributes
            rel_value = anchor.get("rel")
            rel_attrs: list[str] = []
            if isinstance(rel_value, str):
                rel_attrs = rel_value.split()
            elif isinstance(rel_value, list):
                rel_attrs = [str(item) for item in rel_value]

            is_nofollow = "nofollow" in rel_attrs
            is_sponsored = "sponsored" in rel_attrs
            is_ugc = "ugc" in rel_attrs

            yield ExtractedLink(
                source_url=source_url,
                source_domain=source_domain,
                target_url=target_url,
                target_domain=target_domain,
                anchor_text=anchor_text,
                is_nofollow=is_nofollow,
                is_sponsored=is_sponsored,
                is_ugc=is_ugc,
            )

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc

    def _normalize_domain(self, domain: str) -> str:
        """
        Normalize domain (lowercase, remove www prefix).

        Args:
            domain: Domain to normalize

        Returns:
            Normalized domain
        """
        domain = domain.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain


class BacklinkDatasetIngestor:
    """
    Ingestor for Common Crawl domain-level hyperlink graph.

    This provides an alternative to WARC processing by using
    the pre-processed domain graph datasets.
    """

    WEB_GRAPH_BASE = "https://data.commoncrawl.org/projects/hyperlinkgraph"

    def __init__(self, session: Any | None = None) -> None:
        """
        Initialize the BacklinkDatasetIngestor.

        Args:
            session: SQLModel database session (optional, for database operations)
        """
        self.session = session
        self._cc_ingestor = CommonCrawlIngestor()

    async def get_available_datasets(self) -> list[dict[str, Any]]:
        """
        Get list of available hyperlink graph datasets.

        Returns:
            List of available datasets with metadata
        """
        # Common Crawl hyperlink graph datasets follow naming pattern:
        # cc-main-YYYY-mmm (e.g., cc-main-2025-sep-oct-nov)
        # We'll return known recent datasets
        datasets = [
            {
                "id": "cc-main-2025-sep-oct-nov",
                "name": "September-November 2025",
                "host_nodes": 235_700_000,
                "host_edges": 9_500_000_000,
                "domain_nodes": 100_700_000,
                "domain_edges": 6_600_000_000,
            },
            {
                "id": "cc-main-2025-aug-sep-oct",
                "name": "August-October 2025",
                "host_nodes": 468_400_000,
                "host_edges": 8_000_000_000,
                "domain_nodes": 97_700_000,
                "domain_edges": 6_000_000_000,
            },
        ]
        return datasets

    async def download_domain_graph(
        self, dataset_id: str, output_path: str, graph_type: str = "domain"
    ) -> None:
        """
        Download domain-level or host-level graph dataset.

        Args:
            dataset_id: Dataset identifier (e.g., "cc-main-2025-sep-oct-nov")
            output_path: Local path to save the dataset
            graph_type: Type of graph to download ("domain" or "host")

        Raises:
            httpx.HTTPError: If download fails
        """
        # Download the edges file (plain text format: from_id, to_id)
        url = f"{self.WEB_GRAPH_BASE}/{dataset_id}/{graph_type}/edges.txt.gz"

        async with httpx.AsyncClient(timeout=600.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Stream download to handle large files
                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    async def download_vertices(
        self, dataset_id: str, output_path: str, graph_type: str = "domain"
    ) -> None:
        """
        Download vertices file mapping IDs to domain names.

        Args:
            dataset_id: Dataset identifier (e.g., "cc-main-2025-sep-oct-nov")
            output_path: Local path to save the vertices file
            graph_type: Type of graph ("domain" or "host")

        Raises:
            httpx.HTTPError: If download fails
        """
        # Download the vertices file (format: id, rev_domain, num_hosts)
        url = f"{self.WEB_GRAPH_BASE}/{dataset_id}/{graph_type}/vertices.txt.gz"

        async with httpx.AsyncClient(timeout=600.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    async def process_domain_graph(
        self, edges_path: str, vertices_path: str
    ) -> AsyncIterator[tuple[str, str, int]]:
        """
        Process domain graph files and yield domain relationships.

        Args:
            edges_path: Path to the edges.txt.gz file
            vertices_path: Path to the vertices.txt.gz file

        Yields:
            Tuples of (source_domain, target_domain, link_count)
        """
        import gzip

        # Step 1: Load vertices mapping (id -> domain name)
        id_to_domain: dict[int, str] = {}

        with gzip.open(vertices_path, "rt", encoding="utf-8") as vf:
            for line in vf:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    node_id = int(parts[0])
                    # Reverse domain format: com.example -> example.com
                    rev_domain = parts[1]
                    domain = self._unreverse_domain(rev_domain)
                    id_to_domain[node_id] = domain

        # Step 2: Process edges and aggregate by domain pair
        edge_counts: dict[tuple[str, str], int] = {}

        with gzip.open(edges_path, "rt", encoding="utf-8") as ef:
            for line in ef:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    from_id = int(parts[0])
                    to_id = int(parts[1])

                    # Get domain names
                    source_domain = id_to_domain.get(from_id)
                    target_domain = id_to_domain.get(to_id)

                    if source_domain and target_domain:
                        key = (source_domain, target_domain)
                        edge_counts[key] = edge_counts.get(key, 0) + 1

        # Step 3: Yield aggregated results
        for (source_domain, target_domain), count in edge_counts.items():
            yield (source_domain, target_domain, count)

    async def ingest_to_database(
        self,
        snapshot_id: Any,
        edges_path: str,
        vertices_path: str,
        batch_size: int = 1000,
        progress_callback: Any | None = None,
    ) -> dict[str, int]:
        """
        Ingest domain graph data into the database.

        Args:
            snapshot_id: UUID of the LinkSnapshot record
            edges_path: Path to the edges.txt.gz file
            vertices_path: Path to the vertices.txt.gz file
            batch_size: Number of records to insert per batch
            progress_callback: Optional callback function(processed, total)

        Returns:
            Dictionary with ingestion statistics

        Raises:
            ValueError: If session is not provided during initialization
        """
        if not self.session:
            raise ValueError("Database session required for ingestion")

        from datetime import datetime, timezone

        from app.models.links import BacklinkEdge

        edges_inserted = 0
        domains_seen: set[str] = set()
        batch: list[BacklinkEdge] = []
        now = datetime.now(timezone.utc)

        async for source_domain, target_domain, count in self.process_domain_graph(
            edges_path, vertices_path
        ):
            domains_seen.add(source_domain)
            domains_seen.add(target_domain)

            # Create BacklinkEdge records for each link
            # Note: Domain graph doesn't have URL-level or anchor text data
            for _ in range(count):
                edge = BacklinkEdge(
                    snapshot_id=snapshot_id,
                    source_url=f"https://{source_domain}/",
                    target_url=f"https://{target_domain}/",
                    source_domain=source_domain,
                    target_domain=target_domain,
                    anchor_text=None,
                    is_nofollow=False,
                    is_sponsored=False,
                    is_ugc=False,
                    first_seen=now,
                    last_seen=now,
                )
                batch.append(edge)

                if len(batch) >= batch_size:
                    self.session.add_all(batch)
                    self.session.commit()
                    edges_inserted += len(batch)
                    batch = []

                    if progress_callback:
                        progress_callback(edges_inserted, None)

        # Insert remaining batch
        if batch:
            self.session.add_all(batch)
            self.session.commit()
            edges_inserted += len(batch)

        return {
            "edges_inserted": edges_inserted,
            "unique_domains": len(domains_seen),
        }

    async def ingest_warc_backlinks(
        self,
        snapshot_id: Any,
        crawl_id: str,
        url_pattern: str,
        batch_size: int = 1000,
        max_pages: int = 100,
        progress_callback: Any | None = None,
    ) -> dict[str, int]:
        """
        Ingest backlinks from WARC records by querying Common Crawl index.

        This method queries the CC index for pages matching a pattern,
        fetches the WARC records, extracts links, and stores them.

        Args:
            snapshot_id: UUID of the LinkSnapshot record
            crawl_id: Common Crawl dataset ID (e.g., "CC-MAIN-2024-10")
            url_pattern: URL pattern to search for (e.g., "example.com/*")
            batch_size: Number of records to insert per batch
            max_pages: Maximum number of pages to process
            progress_callback: Optional callback function(processed, total)

        Returns:
            Dictionary with ingestion statistics

        Raises:
            ValueError: If session is not provided during initialization
        """
        if not self.session:
            raise ValueError("Database session required for ingestion")

        from datetime import datetime, timezone

        from app.models.links import BacklinkEdge

        # Step 1: Query CC index for matching URLs
        index_results = await self._cc_ingestor.query_index(
            crawl_id, url_pattern, limit=max_pages
        )

        edges_inserted = 0
        pages_processed = 0
        domains_seen: set[str] = set()
        batch: list[BacklinkEdge] = []
        now = datetime.now(timezone.utc)

        # Step 2: Process each WARC record
        for idx, record in enumerate(index_results):
            try:
                # Extract WARC location info
                filename = record.get("filename")
                offset = record.get("offset")
                length = record.get("length")
                source_url = record.get("url")

                if not all([filename, offset is not None, length, source_url]):
                    continue

                # Fetch WARC record
                warc_content = await self._cc_ingestor.fetch_warc_record(
                    filename, offset, length
                )

                # Parse WARC record to extract HTML
                html_content = self._extract_html_from_warc(warc_content)
                if not html_content:
                    continue

                # Extract links from HTML
                for link in self._cc_ingestor.extract_links_from_html(
                    html_content, source_url
                ):
                    domains_seen.add(link.source_domain)
                    domains_seen.add(link.target_domain)

                    edge = BacklinkEdge(
                        snapshot_id=snapshot_id,
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
                    batch.append(edge)

                    if len(batch) >= batch_size:
                        self.session.add_all(batch)
                        self.session.commit()
                        edges_inserted += len(batch)
                        batch = []

                pages_processed += 1

                if progress_callback:
                    progress_callback(pages_processed, len(index_results))

            except Exception as e:
                # Log error but continue processing
                print(f"Error processing WARC record {idx}: {e}")
                continue

        # Insert remaining batch
        if batch:
            self.session.add_all(batch)
            self.session.commit()
            edges_inserted += len(batch)

        return {
            "edges_inserted": edges_inserted,
            "pages_processed": pages_processed,
            "unique_domains": len(domains_seen),
        }

    def _unreverse_domain(self, rev_domain: str) -> str:
        """
        Convert reversed domain format to normal format.

        Args:
            rev_domain: Reversed domain (e.g., "com.example.www")

        Returns:
            Normal domain format (e.g., "www.example.com")
        """
        parts = rev_domain.split(".")
        return ".".join(reversed(parts))

    def _extract_html_from_warc(self, warc_content: bytes) -> str | None:
        """
        Extract HTML content from WARC record.

        Args:
            warc_content: Raw WARC record bytes

        Returns:
            HTML content as string, or None if not HTML
        """
        try:
            from io import BytesIO

            from warcio.archiveiterator import ArchiveIterator

            # Parse WARC record
            stream = BytesIO(warc_content)
            for record in ArchiveIterator(stream):
                # Check if it's an HTML response
                content_type = record.http_headers.get_header("Content-Type", "")
                if "text/html" in content_type:
                    # Read and decode content
                    html_bytes = record.content_stream().read()
                    # Try common encodings
                    for encoding in ["utf-8", "latin-1", "iso-8859-1"]:
                        try:
                            return html_bytes.decode(encoding)
                        except UnicodeDecodeError:
                            continue
            return None
        except Exception:
            return None
