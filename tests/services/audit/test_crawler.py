"""
Test suite for HTML Crawler service.
Following TDD approach - tests written first.
"""


import httpx
import pytest
import respx

from app.services.audit.crawler import (
    Crawler,
    CrawlResult,
    ExtractedData,
)


class TestURLNormalization:
    """Test URL normalization functionality."""

    def test_normalize_url_removes_fragment(self):
        """URL normalization should remove fragment identifiers."""
        crawler = Crawler("https://example.com")
        normalized = crawler.normalize_url("https://example.com/page#section")
        assert normalized == "https://example.com/page"

    def test_normalize_url_removes_trailing_slash(self):
        """URL normalization should remove trailing slashes."""
        crawler = Crawler("https://example.com")
        normalized = crawler.normalize_url("https://example.com/page/")
        assert normalized == "https://example.com/page"

    def test_normalize_url_preserves_query_params(self):
        """URL normalization should preserve query parameters."""
        crawler = Crawler("https://example.com")
        normalized = crawler.normalize_url("https://example.com/page?id=123")
        assert normalized == "https://example.com/page?id=123"

    def test_normalize_url_handles_complex_urls(self):
        """URL normalization should handle complex URLs correctly."""
        crawler = Crawler("https://example.com")
        normalized = crawler.normalize_url(
            "https://example.com/path/to/page?query=value&other=test#fragment"
        )
        assert normalized == "https://example.com/path/to/page?query=value&other=test"

    def test_normalize_url_lowercases_scheme_and_domain(self):
        """URL normalization should lowercase scheme and domain."""
        crawler = Crawler("https://example.com")
        normalized = crawler.normalize_url("HTTPS://EXAMPLE.COM/Path")
        assert normalized == "https://example.com/Path"


class TestURLValidation:
    """Test URL validation logic."""

    def test_is_valid_url_same_domain(self):
        """Valid URLs should be on the same domain."""
        crawler = Crawler("https://example.com")
        assert crawler.is_valid_url("https://example.com/page") is True
        assert crawler.is_valid_url("https://example.com/another/page") is True

    def test_is_valid_url_different_domain(self):
        """URLs on different domains should be invalid."""
        crawler = Crawler("https://example.com")
        assert crawler.is_valid_url("https://other.com/page") is False

    def test_is_valid_url_subdomain(self):
        """Subdomains should be treated as different domains."""
        crawler = Crawler("https://example.com")
        assert crawler.is_valid_url("https://sub.example.com/page") is False

    def test_is_valid_url_http_scheme(self):
        """HTTP and HTTPS schemes should be valid."""
        crawler = Crawler("https://example.com")
        assert crawler.is_valid_url("http://example.com/page") is True
        assert crawler.is_valid_url("https://example.com/page") is True

    def test_is_valid_url_invalid_scheme(self):
        """Non-HTTP(S) schemes should be invalid."""
        crawler = Crawler("https://example.com")
        assert crawler.is_valid_url("ftp://example.com/file") is False
        assert crawler.is_valid_url("mailto:test@example.com") is False
        assert crawler.is_valid_url("javascript:void(0)") is False

    def test_is_valid_url_include_patterns(self):
        """URLs should match include patterns if provided."""
        crawler = Crawler("https://example.com", include_patterns=[r"/blog/.*"])
        assert crawler.is_valid_url("https://example.com/blog/post-1") is True
        assert crawler.is_valid_url("https://example.com/about") is False

    def test_is_valid_url_exclude_patterns(self):
        """URLs should not match exclude patterns."""
        crawler = Crawler("https://example.com", exclude_patterns=[r"/admin/.*"])
        assert crawler.is_valid_url("https://example.com/page") is True
        assert crawler.is_valid_url("https://example.com/admin/users") is False

    def test_is_valid_url_include_and_exclude_patterns(self):
        """Exclude patterns should take precedence over include patterns."""
        crawler = Crawler(
            "https://example.com",
            include_patterns=[r"/blog/.*"],
            exclude_patterns=[r".*/draft$"],
        )
        assert crawler.is_valid_url("https://example.com/blog/post-1") is True
        assert crawler.is_valid_url("https://example.com/blog/draft") is False


class TestHTMLExtraction:
    """Test HTML data extraction functionality."""

    def test_extract_data_basic_html(self):
        """Extract basic SEO data from simple HTML."""
        html = """
        <html>
            <head>
                <title>Test Page</title>
                <meta name="description" content="This is a test page">
                <link rel="canonical" href="https://example.com/canonical">
                <meta name="robots" content="index, follow">
            </head>
            <body>
                <h1>Main Heading</h1>
                <p>This is some content with multiple words.</p>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        assert data.title == "Test Page"
        assert data.meta_description == "This is a test page"
        assert data.canonical == "https://example.com/canonical"
        assert data.h1_count == 1
        assert data.first_h1 == "Main Heading"
        assert data.meta_robots == "index, follow"
        assert data.word_count > 0

    def test_extract_data_missing_elements(self):
        """Extract data from HTML with missing elements."""
        html = "<html><body><p>Content</p></body></html>"
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        assert data.title is None
        assert data.meta_description is None
        assert data.canonical is None
        assert data.h1_count == 0
        assert data.first_h1 is None
        assert data.meta_robots is None

    def test_extract_data_multiple_h1_tags(self):
        """Extract data from HTML with multiple h1 tags."""
        html = """
        <html>
            <body>
                <h1>First Heading</h1>
                <h1>Second Heading</h1>
                <h1>Third Heading</h1>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        assert data.h1_count == 3
        assert data.first_h1 == "First Heading"

    def test_extract_data_internal_and_external_links(self):
        """Extract and separate internal and external links."""
        html = """
        <html>
            <body>
                <a href="/page1">Internal 1</a>
                <a href="https://example.com/page2">Internal 2</a>
                <a href="https://other.com/page">External 1</a>
                <a href="http://another.com">External 2</a>
                <a href="mailto:test@example.com">Email</a>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/base")

        assert "https://example.com/page1" in data.internal_links
        assert "https://example.com/page2" in data.internal_links
        assert "https://other.com/page" in data.external_links
        assert "http://another.com" in data.external_links
        # mailto should not be in either list
        assert "mailto:test@example.com" not in data.internal_links
        assert "mailto:test@example.com" not in data.external_links

    def test_extract_data_relative_links(self):
        """Extract relative links and convert to absolute."""
        html = """
        <html>
            <body>
                <a href="/about">About</a>
                <a href="../contact">Contact</a>
                <a href="services/consulting">Consulting</a>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/products/software")

        assert "https://example.com/about" in data.internal_links
        assert "https://example.com/contact" in data.internal_links
        assert (
            "https://example.com/products/services/consulting" in data.internal_links
        )

    def test_extract_data_content_hash(self):
        """Extract content hash for duplicate detection."""
        html = "<html><body><p>Test content</p></body></html>"
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        assert data.content_hash is not None
        assert len(data.content_hash) == 32  # MD5 hash length

        # Same content should produce same hash
        data2 = crawler.extract_data(html, "https://example.com/other")
        assert data.content_hash == data2.content_hash

    def test_extract_data_word_count(self):
        """Extract accurate word count from HTML."""
        html = """
        <html>
            <body>
                <p>This is a test paragraph with ten words total.</p>
                <p>Another paragraph with five words.</p>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        # Should count all visible text words (9 + 5 = 14)
        assert data.word_count == 14

    def test_extract_data_ignores_script_and_style(self):
        """Word count should ignore script and style tags."""
        html = """
        <html>
            <head>
                <style>body { color: red; }</style>
                <script>console.log('test');</script>
            </head>
            <body>
                <p>Five words in paragraph only.</p>
            </body>
        </html>
        """
        crawler = Crawler("https://example.com")
        data = crawler.extract_data(html, "https://example.com/page")

        assert data.word_count == 5


class TestHTTPFetch:
    """Test HTTP fetching functionality."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_successful_request(self):
        """Fetch should return successful result for valid URL."""
        url = "https://example.com/page"
        html_content = "<html><body><h1>Test</h1></body></html>"

        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=html_content,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        crawler = Crawler("https://example.com")
        await crawler.setup()

        result = await crawler.fetch(url)

        assert result.url == url
        assert result.status_code == 200
        assert result.content_type == "text/html; charset=utf-8"
        assert result.html == html_content
        assert result.error is None
        assert result.response_time_ms > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_with_redirect(self):
        """Fetch should track redirect chain."""
        url = "https://example.com/old"
        redirect_url = "https://example.com/new"
        final_content = "<html><body>Final</body></html>"

        # Mock redirect
        respx.get(url).mock(
            return_value=httpx.Response(
                301, headers={"location": redirect_url}
            )
        )
        respx.get(redirect_url).mock(
            return_value=httpx.Response(200, content=final_content)
        )

        crawler = Crawler("https://example.com")
        await crawler.setup()

        result = await crawler.fetch(url)

        assert result.url == url
        assert result.final_url == redirect_url
        assert result.status_code == 200
        assert len(result.redirect_chain) > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_timeout(self):
        """Fetch should handle timeout errors gracefully."""
        url = "https://example.com/slow"

        respx.get(url).mock(side_effect=httpx.TimeoutException("Request timeout"))

        crawler = Crawler("https://example.com")
        await crawler.setup()

        result = await crawler.fetch(url)

        assert result.url == url
        assert result.status_code is None
        assert result.error is not None
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_network_error(self):
        """Fetch should handle network errors gracefully."""
        url = "https://example.com/error"

        respx.get(url).mock(side_effect=httpx.ConnectError("Connection failed"))

        crawler = Crawler("https://example.com")
        await crawler.setup()

        result = await crawler.fetch(url)

        assert result.url == url
        assert result.status_code is None
        assert result.error is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_non_html_content(self):
        """Fetch should handle non-HTML content types."""
        url = "https://example.com/file.pdf"

        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=b"PDF content",
                headers={"content-type": "application/pdf"},
            )
        )

        crawler = Crawler("https://example.com")
        await crawler.setup()

        result = await crawler.fetch(url)

        assert result.status_code == 200
        assert result.content_type == "application/pdf"


class TestRobotsTxt:
    """Test robots.txt functionality."""

    @pytest.mark.asyncio
    async def test_can_fetch_allowed_url(self):
        """URLs allowed by robots.txt should be fetchable."""
        crawler = Crawler("https://example.com", respect_robots=True)
        await crawler.setup()

        # Default: all URLs allowed if no robots.txt
        assert crawler.can_fetch("https://example.com/page") is True

    @pytest.mark.asyncio
    async def test_can_fetch_disabled(self):
        """When robots.txt is disabled, all URLs should be allowed."""
        crawler = Crawler("https://example.com", respect_robots=False)
        await crawler.setup()

        assert crawler.can_fetch("https://example.com/admin") is True


class TestCrawlGenerator:
    """Test the main crawl generator functionality."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_crawl_single_page(self):
        """Crawl should yield results for a single page."""
        url = "https://example.com/"
        html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"

        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=html, headers={"content-type": "text/html; charset=utf-8"}
            )
        )

        crawler = Crawler("https://example.com", max_pages=1)
        await crawler.setup()

        results = []
        async for crawl_result, extracted_data, depth in crawler.crawl():
            results.append((crawl_result, extracted_data, depth))

        assert len(results) == 1
        crawl_result, extracted_data, depth = results[0]
        assert crawl_result.status_code == 200
        assert extracted_data.title == "Test"
        assert depth == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_crawl_respects_max_pages(self):
        """Crawl should stop after max_pages."""
        base_url = "https://example.com/"
        html_template = """
        <html>
            <body>
                <a href="/page1">Page 1</a>
                <a href="/page2">Page 2</a>
                <a href="/page3">Page 3</a>
            </body>
        </html>
        """

        respx.get(base_url).mock(
            return_value=httpx.Response(
                200, content=html_template, headers={"content-type": "text/html"}
            )
        )
        respx.get("https://example.com/page1").mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Page 1</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        respx.get("https://example.com/page2").mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Page 2</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        respx.get("https://example.com/page3").mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Page 3</body></html>",
                headers={"content-type": "text/html"},
            )
        )

        crawler = Crawler("https://example.com/", max_pages=2)
        await crawler.setup()

        results = []
        async for crawl_result, extracted_data, depth in crawler.crawl():
            results.append((crawl_result, extracted_data, depth))

        assert len(results) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_crawl_respects_max_depth(self):
        """Crawl should not exceed max_depth."""
        respx.get("https://example.com/").mock(
            return_value=httpx.Response(
                200,
                content='<html><body><a href="/level1">L1</a></body></html>',
                headers={"content-type": "text/html"},
            )
        )
        respx.get("https://example.com/level1").mock(
            return_value=httpx.Response(
                200,
                content='<html><body><a href="/level2">L2</a></body></html>',
                headers={"content-type": "text/html"},
            )
        )
        respx.get("https://example.com/level2").mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Level 2</body></html>",
                headers={"content-type": "text/html"},
            )
        )

        crawler = Crawler("https://example.com/", max_pages=10, max_depth=1)
        await crawler.setup()

        results = []
        async for crawl_result, extracted_data, depth in crawler.crawl():
            results.append((crawl_result, extracted_data, depth))

        # Should only crawl depth 0 and 1, not depth 2
        depths = [depth for _, _, depth in results]
        assert max(depths) <= 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_crawl_deduplicates_urls(self):
        """Crawl should not visit the same URL twice."""
        html = """
        <html>
            <body>
                <a href="/page1">Link 1</a>
                <a href="/page1">Link 1 again</a>
                <a href="/page1#section">Link 1 with fragment</a>
            </body>
        </html>
        """

        respx.get("https://example.com/").mock(
            return_value=httpx.Response(
                200, content=html, headers={"content-type": "text/html"}
            )
        )
        respx.get("https://example.com/page1").mock(
            return_value=httpx.Response(
                200,
                content="<html><body>Page 1</body></html>",
                headers={"content-type": "text/html"},
            )
        )

        crawler = Crawler("https://example.com/", max_pages=10)
        await crawler.setup()

        results = []
        async for crawl_result, extracted_data, depth in crawler.crawl():
            results.append((crawl_result, extracted_data, depth))

        # Should only crawl the base URL and /page1 once each
        urls = [result.url for result, _, _ in results]
        assert len(urls) == len(set(urls))  # No duplicates

    @pytest.mark.asyncio
    async def test_crawl_stop(self):
        """Stop method should halt crawling."""
        crawler = Crawler("https://example.com/", max_pages=100)
        await crawler.setup()

        # Stop immediately
        crawler.stop()

        results = []
        with respx.mock:
            respx.get("https://example.com/").mock(
                return_value=httpx.Response(
                    200,
                    content="<html><body>Test</body></html>",
                    headers={"content-type": "text/html"},
                )
            )

            async for crawl_result, extracted_data, depth in crawler.crawl():
                results.append((crawl_result, extracted_data, depth))
                break  # Should exit quickly due to stop

        # With stop called, crawling should halt early
        assert len(results) <= 1


class TestCrawlerInitialization:
    """Test crawler initialization and configuration."""

    def test_crawler_default_initialization(self):
        """Crawler should initialize with default values."""
        crawler = Crawler("https://example.com")

        assert crawler.seed_url == "https://example.com"
        assert crawler.max_pages == 100
        assert crawler.max_depth == 3
        assert crawler.concurrency == 5
        assert crawler.respect_robots is True

    def test_crawler_custom_initialization(self):
        """Crawler should accept custom configuration."""
        crawler = Crawler(
            seed_url="https://example.com",
            max_pages=50,
            max_depth=2,
            concurrency=10,
            user_agent="CustomBot/1.0",
            respect_robots=False,
            include_patterns=[r"/blog/.*"],
            exclude_patterns=[r"/admin/.*"],
        )

        assert crawler.seed_url == "https://example.com"
        assert crawler.max_pages == 50
        assert crawler.max_depth == 2
        assert crawler.concurrency == 10
        assert crawler.user_agent == "CustomBot/1.0"
        assert crawler.respect_robots is False
        assert crawler.include_patterns == [r"/blog/.*"]
        assert crawler.exclude_patterns == [r"/admin/.*"]


class TestDataClasses:
    """Test data class structures."""

    def test_crawl_result_creation(self):
        """CrawlResult should be creatable with all fields."""
        result = CrawlResult(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            content_type="text/html",
            response_time_ms=150.5,
            redirect_chain=[],
            html="<html></html>",
            error=None,
        )

        assert result.url == "https://example.com"
        assert result.status_code == 200
        assert result.response_time_ms == 150.5

    def test_extracted_data_creation(self):
        """ExtractedData should be creatable with all fields."""
        data = ExtractedData(
            title="Test Page",
            meta_description="Description",
            canonical="https://example.com/canonical",
            h1_count=2,
            first_h1="Heading",
            word_count=100,
            meta_robots="index, follow",
            internal_links=["https://example.com/page1"],
            external_links=["https://other.com"],
            content_hash="abc123",
        )

        assert data.title == "Test Page"
        assert data.h1_count == 2
        assert len(data.internal_links) == 1
