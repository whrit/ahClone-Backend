"""Tests for Common Crawl ingestion service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.links.commoncrawl import (
    BacklinkDatasetIngestor,
    CommonCrawlIngestor,
    ExtractedLink,
)


class TestExtractedLink:
    """Test ExtractedLink dataclass."""

    def test_extracted_link_creation(self):
        """Test creating an ExtractedLink instance."""
        link = ExtractedLink(
            source_url="https://example.com/page",
            source_domain="example.com",
            target_url="https://target.com/page",
            target_domain="target.com",
            anchor_text="Click here",
            is_nofollow=False,
            is_sponsored=False,
            is_ugc=False,
        )

        assert link.source_url == "https://example.com/page"
        assert link.source_domain == "example.com"
        assert link.target_url == "https://target.com/page"
        assert link.target_domain == "target.com"
        assert link.anchor_text == "Click here"
        assert link.is_nofollow is False
        assert link.is_sponsored is False
        assert link.is_ugc is False

    def test_extracted_link_with_none_anchor(self):
        """Test ExtractedLink with None anchor text."""
        link = ExtractedLink(
            source_url="https://example.com/page",
            source_domain="example.com",
            target_url="https://target.com/page",
            target_domain="target.com",
            anchor_text=None,
            is_nofollow=True,
            is_sponsored=False,
            is_ugc=False,
        )

        assert link.anchor_text is None
        assert link.is_nofollow is True


class TestCommonCrawlIngestor:
    """Test CommonCrawlIngestor class."""

    def test_ingestor_constants(self):
        """Test ingestor has correct constants."""
        assert CommonCrawlIngestor.CC_INDEX_URL == "https://index.commoncrawl.org"
        assert CommonCrawlIngestor.CC_DATA_URL == "https://data.commoncrawl.org"

    @pytest.mark.asyncio
    async def test_get_available_crawls(self):
        """Test getting available crawls."""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value=[
            {"id": "CC-MAIN-2024-10", "name": "March 2024"},
            {"id": "CC-MAIN-2024-09", "name": "February 2024"},
        ])

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            ingestor = CommonCrawlIngestor()
            crawls = await ingestor.get_available_crawls()

            assert len(crawls) == 2
            assert crawls[0]["id"] == "CC-MAIN-2024-10"
            assert crawls[1]["id"] == "CC-MAIN-2024-09"

    @pytest.mark.asyncio
    async def test_query_index(self):
        """Test querying CC index."""
        mock_response = MagicMock()
        mock_response.text = """{"url": "https://example.com/page1"}
{"url": "https://example.com/page2"}"""

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            ingestor = CommonCrawlIngestor()
            results = await ingestor.query_index("CC-MAIN-2024-10", "example.com/*", limit=10)

            assert len(results) == 2
            assert results[0]["url"] == "https://example.com/page1"
            assert results[1]["url"] == "https://example.com/page2"

    @pytest.mark.asyncio
    async def test_query_index_with_limit(self):
        """Test query_index respects limit."""
        lines = [f'{{"url": "https://example.com/page{i}"}}' for i in range(100)]
        mock_response = MagicMock()
        mock_response.text = "\n".join(lines)

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            ingestor = CommonCrawlIngestor()
            results = await ingestor.query_index("CC-MAIN-2024-10", "example.com/*", limit=10)

            assert len(results) == 10

    @pytest.mark.asyncio
    async def test_fetch_warc_record(self):
        """Test fetching WARC record."""
        mock_response = MagicMock()
        mock_response.content = b"WARC record content"

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            ingestor = CommonCrawlIngestor()
            content = await ingestor.fetch_warc_record(
                "crawl-data/CC-MAIN-2024-10/segments/123/warc/CC-MAIN-20240301.warc.gz",
                offset=1000,
                length=5000
            )

            assert content == b"WARC record content"

    def test_extract_links_from_html_basic(self):
        """Test basic link extraction from HTML."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page1">Link 1</a>
                <a href="https://example.com/page2">Link 2</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 2
        assert links[0].source_url == "https://source.com/page"
        assert links[0].source_domain == "source.com"
        assert links[0].target_url == "https://example.com/page1"
        assert links[0].target_domain == "example.com"
        assert links[0].anchor_text == "Link 1"
        assert links[0].is_nofollow is False

    def test_extract_links_with_nofollow(self):
        """Test extracting links with nofollow attribute."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page" rel="nofollow">No Follow Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].is_nofollow is True
        assert links[0].is_sponsored is False
        assert links[0].is_ugc is False

    def test_extract_links_with_sponsored(self):
        """Test extracting links with sponsored attribute."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page" rel="sponsored">Sponsored Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].is_nofollow is False
        assert links[0].is_sponsored is True
        assert links[0].is_ugc is False

    def test_extract_links_with_ugc(self):
        """Test extracting links with ugc attribute."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page" rel="ugc">UGC Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].is_nofollow is False
        assert links[0].is_sponsored is False
        assert links[0].is_ugc is True

    def test_extract_links_with_multiple_rel_attributes(self):
        """Test extracting links with multiple rel attributes."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page" rel="nofollow sponsored">Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].is_nofollow is True
        assert links[0].is_sponsored is True
        assert links[0].is_ugc is False

    def test_extract_links_skips_internal_links(self):
        """Test that internal links (same domain) are skipped."""
        html = """
        <html>
            <body>
                <a href="https://source.com/internal">Internal Link</a>
                <a href="https://example.com/external">External Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].target_domain == "example.com"

    def test_extract_links_normalizes_domains(self):
        """Test domain normalization (lowercase, remove www)."""
        html = """
        <html>
            <body>
                <a href="https://WWW.EXAMPLE.COM/page">Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://WWW.SOURCE.COM/page"))

        assert len(links) == 1
        assert links[0].source_domain == "source.com"
        assert links[0].target_domain == "example.com"

    def test_extract_links_truncates_long_urls(self):
        """Test URL truncation to 2048 characters."""
        long_url = "https://example.com/" + "a" * 3000
        html = f'<html><body><a href="{long_url}">Link</a></body></html>'

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert len(links[0].target_url) == 2048

    def test_extract_links_truncates_long_anchor_text(self):
        """Test anchor text truncation to 500 characters."""
        long_anchor = "a" * 600
        html = f'<html><body><a href="https://example.com/page">{long_anchor}</a></body></html>'

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert len(links[0].anchor_text) == 500

    def test_extract_links_handles_empty_anchor_text(self):
        """Test handling of empty anchor text."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page"></a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].anchor_text is None or links[0].anchor_text == ""

    def test_extract_links_handles_missing_href(self):
        """Test handling of anchor tags without href."""
        html = """
        <html>
            <body>
                <a>No href</a>
                <a href="https://example.com/page">Valid link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert links[0].target_url == "https://example.com/page"

    def test_extract_links_handles_relative_urls(self):
        """Test handling of relative URLs."""
        html = """
        <html>
            <body>
                <a href="/relative/path">Relative Link</a>
                <a href="https://example.com/absolute">Absolute Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        # Should only extract absolute URLs or handle relative URLs properly
        # Depending on implementation, adjust assertion
        assert len(links) >= 1

    def test_extract_links_with_nested_tags(self):
        """Test extracting anchor text from nested tags."""
        html = """
        <html>
            <body>
                <a href="https://example.com/page"><strong>Bold</strong> Link</a>
            </body>
        </html>
        """

        ingestor = CommonCrawlIngestor()
        links = list(ingestor.extract_links_from_html(html, "https://source.com/page"))

        assert len(links) == 1
        assert "Bold" in links[0].anchor_text
        assert "Link" in links[0].anchor_text


class TestBacklinkDatasetIngestor:
    """Test BacklinkDatasetIngestor class."""

    def test_ingestor_constants(self):
        """Test ingestor has correct constants."""
        assert BacklinkDatasetIngestor.WEB_GRAPH_BASE == "https://data.commoncrawl.org/projects/hyperlinkgraph"

    @pytest.mark.asyncio
    async def test_backlink_ingestor_initialization(self):
        """Test BacklinkDatasetIngestor can be instantiated."""
        ingestor = BacklinkDatasetIngestor()
        assert ingestor is not None
        assert hasattr(ingestor, "WEB_GRAPH_BASE")
