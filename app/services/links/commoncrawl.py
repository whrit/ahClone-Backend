"""Common Crawl ingestion service for backlink data."""

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

    async def get_available_datasets(self) -> list[dict[str, Any]]:
        """
        Get list of available hyperlink graph datasets.

        Returns:
            List of available datasets
        """
        # Implementation would fetch and parse available datasets
        # from the hyperlink graph project
        async with httpx.AsyncClient() as client:
            # This is a placeholder - actual implementation would
            # parse the CC hyperlink graph index
            await client.get(self.WEB_GRAPH_BASE)
            # Parse and return available datasets
            return []

    async def download_domain_graph(
        self, dataset_id: str, output_path: str
    ) -> None:
        """
        Download domain-level graph dataset.

        Args:
            dataset_id: Dataset identifier
            output_path: Local path to save the dataset
        """
        # Implementation would download the specified dataset
        async with httpx.AsyncClient() as client:
            url = f"{self.WEB_GRAPH_BASE}/{dataset_id}"
            response = await client.get(url)
            # Save to output_path
            with open(output_path, "wb") as f:
                f.write(response.content)

    async def process_domain_graph(
        self, file_path: str
    ) -> AsyncIterator[tuple[str, str, int]]:
        """
        Process domain graph file.

        Args:
            file_path: Path to the domain graph file

        Yields:
            Tuples of (source_domain, target_domain, link_count)
        """
        # Implementation would parse the domain graph format
        # and yield domain-to-domain relationships
        # This is a placeholder for the actual implementation
        if False:  # Placeholder to make this an async generator
            yield ("", "", 0)
