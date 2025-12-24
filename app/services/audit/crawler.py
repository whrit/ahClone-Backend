"""
HTML Crawler Service for SEO Auditing.

This module provides web crawling functionality with support for:
- Async HTTP requests with httpx
- Robots.txt compliance
- URL normalization and deduplication
- HTML parsing and SEO data extraction
- Configurable crawl depth and page limits
"""

import asyncio
import hashlib
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup


@dataclass
class CrawlResult:
    """Result of crawling a single URL."""

    url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    response_time_ms: float
    redirect_chain: list[str]
    html: str | None
    error: str | None


@dataclass
class ExtractedData:
    """SEO data extracted from HTML."""

    title: str | None
    meta_description: str | None
    canonical: str | None
    h1_count: int
    first_h1: str | None
    word_count: int
    meta_robots: str | None
    internal_links: list[str]
    external_links: list[str]
    content_hash: str


class Crawler:
    """
    Async web crawler for SEO auditing.

    Crawls a website starting from a seed URL, respecting robots.txt,
    following links, and extracting SEO-relevant data from each page.
    """

    def __init__(
        self,
        seed_url: str,
        max_pages: int = 100,
        max_depth: int = 3,
        concurrency: int = 5,
        user_agent: str = "SEO-Audit-Bot/1.0",
        respect_robots: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        """
        Initialize the crawler.

        Args:
            seed_url: Starting URL for the crawl
            max_pages: Maximum number of pages to crawl
            max_depth: Maximum crawl depth from seed URL
            concurrency: Number of concurrent requests
            user_agent: User agent string for requests
            respect_robots: Whether to respect robots.txt
            include_patterns: List of regex patterns - only URLs matching these will be crawled
            exclude_patterns: List of regex patterns - URLs matching these will be excluded
        """
        self.seed_url = seed_url
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.concurrency = concurrency
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []

        # Parse seed URL for domain extraction
        parsed = urlparse(seed_url)
        self.domain = parsed.netloc
        self.scheme = parsed.scheme

        # State tracking
        self.visited: set[str] = set()
        self.robots_parser: RobotFileParser | None = None
        self.client: httpx.AsyncClient | None = None
        self._stop_flag = False

        # Compile regex patterns
        self.include_regex = [re.compile(pattern) for pattern in self.include_patterns]
        self.exclude_regex = [re.compile(pattern) for pattern in self.exclude_patterns]

    async def setup(self) -> None:
        """Initialize the crawler (async setup)."""
        # Create HTTP client
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        )

        # Load robots.txt if needed
        if self.respect_robots:
            await self._load_robots_txt()

    async def _load_robots_txt(self) -> None:
        """Load and parse robots.txt for the domain."""
        robots_url = f"{self.scheme}://{self.domain}/robots.txt"
        robots_loaded = False

        try:
            if self.client:
                response = await self.client.get(robots_url)
                if response.status_code == 200:
                    # Parse robots.txt content
                    self.robots_parser = RobotFileParser()
                    self.robots_parser.parse(response.text.splitlines())
                    robots_loaded = True
        except Exception:
            # If robots.txt doesn't exist or fails to load, allow all
            pass

        # If robots.txt doesn't exist or failed to load, set parser to None
        # This signals that all URLs are allowed
        if not robots_loaded:
            self.robots_parser = None

    def can_fetch(self, url: str) -> bool:
        """
        Check if URL can be fetched according to robots.txt.

        Args:
            url: URL to check

        Returns:
            True if URL can be fetched, False otherwise
        """
        if not self.respect_robots or not self.robots_parser:
            return True

        try:
            return self.robots_parser.can_fetch(self.user_agent, url)
        except Exception:
            # On error, allow the fetch
            return True

    def is_valid_url(self, url: str) -> bool:
        """
        Check if URL should be crawled.

        Validates:
        - Same domain as seed URL
        - HTTP or HTTPS scheme
        - Include/exclude pattern matching

        Args:
            url: URL to validate

        Returns:
            True if URL should be crawled, False otherwise
        """
        try:
            parsed = urlparse(url)

            # Check scheme
            if parsed.scheme not in ("http", "https"):
                return False

            # Check domain (must match seed domain exactly)
            if parsed.netloc != self.domain:
                return False

            # Check include patterns (if specified, URL must match at least one)
            if self.include_regex:
                if not any(pattern.search(url) for pattern in self.include_regex):
                    return False

            # Check exclude patterns (if URL matches any, exclude it)
            if self.exclude_regex:
                if any(pattern.search(url) for pattern in self.exclude_regex):
                    return False

            return True

        except Exception:
            return False

    def normalize_url(self, url: str) -> str:
        """
        Normalize URL for deduplication.

        - Removes fragment identifiers (#section)
        - Removes trailing slashes from paths
        - Lowercases scheme and domain
        - Preserves query parameters

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        parsed = urlparse(url)

        # Lowercase scheme and domain
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Remove trailing slash from path (but keep it for root)
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Reconstruct URL without fragment
        normalized = urlunparse(
            (scheme, netloc, path, parsed.params, parsed.query, "")  # Empty fragment
        )

        return normalized

    async def fetch(self, url: str) -> CrawlResult:
        """
        Fetch a single URL and return the result.

        Args:
            url: URL to fetch

        Returns:
            CrawlResult with response data or error information
        """
        start_time = time.time()
        redirect_chain: list[str] = []

        try:
            if not self.client:
                raise RuntimeError("Client not initialized - call setup() first")

            response = await self.client.get(url)

            # Track redirect chain
            for resp in response.history:
                redirect_chain.append(str(resp.url))

            # Calculate response time
            response_time_ms = (time.time() - start_time) * 1000

            # Get final URL (after redirects)
            final_url = str(response.url)

            # Get content type
            content_type = response.headers.get("content-type", "")

            # Get HTML content if it's HTML
            html = None
            if "text/html" in content_type.lower():
                html = response.text

            return CrawlResult(
                url=url,
                final_url=final_url,
                status_code=response.status_code,
                content_type=content_type,
                response_time_ms=response_time_ms,
                redirect_chain=redirect_chain,
                html=html,
                error=None,
            )

        except httpx.TimeoutException as e:
            return CrawlResult(
                url=url,
                final_url=None,
                status_code=None,
                content_type=None,
                response_time_ms=(time.time() - start_time) * 1000,
                redirect_chain=redirect_chain,
                html=None,
                error=f"Request timeout: {str(e)}",
            )

        except httpx.ConnectError as e:
            return CrawlResult(
                url=url,
                final_url=None,
                status_code=None,
                content_type=None,
                response_time_ms=(time.time() - start_time) * 1000,
                redirect_chain=redirect_chain,
                html=None,
                error=f"Connection error: {str(e)}",
            )

        except Exception as e:
            return CrawlResult(
                url=url,
                final_url=None,
                status_code=None,
                content_type=None,
                response_time_ms=(time.time() - start_time) * 1000,
                redirect_chain=redirect_chain,
                html=None,
                error=f"Error: {str(e)}",
            )

    def extract_data(self, html: str, base_url: str) -> ExtractedData:
        """
        Extract SEO data from HTML.

        Args:
            html: HTML content to parse
            base_url: Base URL for resolving relative links

        Returns:
            ExtractedData with extracted SEO information
        """
        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text().strip() if title_tag else None

        # Extract meta description
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = None
        if meta_desc_tag:
            content = meta_desc_tag.get("content")
            if isinstance(content, str):
                meta_description = content.strip()

        # Extract canonical URL
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        canonical = None
        if canonical_tag:
            href = canonical_tag.get("href")
            if isinstance(href, str):
                canonical = href

        # Extract meta robots
        meta_robots_tag = soup.find("meta", attrs={"name": "robots"})
        meta_robots = None
        if meta_robots_tag:
            content = meta_robots_tag.get("content")
            if isinstance(content, str):
                meta_robots = content

        # Extract h1 tags
        h1_tags = soup.find_all("h1")
        h1_count = len(h1_tags)
        first_h1 = h1_tags[0].get_text().strip() if h1_tags else None

        # Extract all links
        internal_links: list[str] = []
        external_links: list[str] = []

        for link in soup.find_all("a", href=True):
            href_attr = link.get("href", "")

            # href could be a list or None, ensure it's a string
            if not href_attr or not isinstance(href_attr, str):
                continue

            href = href_attr

            # Skip empty hrefs and non-HTTP(S) schemes
            if not href:
                continue

            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)

            # Parse the URL
            parsed = urlparse(absolute_url)

            # Skip non-HTTP(S) URLs (mailto, javascript, etc.)
            if parsed.scheme not in ("http", "https"):
                continue

            # Normalize the URL
            normalized_url = self.normalize_url(absolute_url)

            # Categorize as internal or external
            if parsed.netloc == self.domain:
                if normalized_url not in internal_links:
                    internal_links.append(normalized_url)
            else:
                if normalized_url not in external_links:
                    external_links.append(normalized_url)

        # Calculate word count (exclude script and style tags)
        for script in soup(["script", "style"]):
            script.decompose()

        text = soup.get_text(separator=" ", strip=True)
        words = text.split()
        word_count = len(words)

        # Calculate content hash (for duplicate detection)
        content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()

        return ExtractedData(
            title=title,
            meta_description=meta_description,
            canonical=canonical,
            h1_count=h1_count,
            first_h1=first_h1,
            word_count=word_count,
            meta_robots=meta_robots,
            internal_links=internal_links,
            external_links=external_links,
            content_hash=content_hash,
        )

    async def crawl(self) -> AsyncGenerator[tuple[CrawlResult, ExtractedData, int], None]:
        """
        Crawl the website starting from seed URL.

        Yields:
            Tuple of (CrawlResult, ExtractedData, depth) for each crawled page
        """
        # Queue of (url, depth) tuples to crawl
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        await queue.put((self.seed_url, 0))

        # Track pages crawled
        pages_crawled = 0

        while not queue.empty() and not self._stop_flag:
            # Check if we've reached max pages
            if pages_crawled >= self.max_pages:
                break

            # Get next URL to crawl
            url, depth = await queue.get()

            # Normalize URL for deduplication
            normalized_url = self.normalize_url(url)

            # Skip if already visited
            if normalized_url in self.visited:
                continue

            # Mark as visited
            self.visited.add(normalized_url)

            # Check if we can fetch this URL
            if not self.can_fetch(normalized_url):
                continue

            # Fetch the URL
            crawl_result = await self.fetch(normalized_url)

            # If fetch was successful and we got HTML, extract data
            extracted_data = None
            if crawl_result.html:
                extracted_data = self.extract_data(crawl_result.html, normalized_url)

                # If we haven't exceeded max depth, add links to queue
                if depth < self.max_depth:
                    for link in extracted_data.internal_links:
                        if self.is_valid_url(link) and self.normalize_url(
                            link
                        ) not in self.visited:
                            await queue.put((link, depth + 1))

            # Create default ExtractedData if none was extracted
            if extracted_data is None:
                extracted_data = ExtractedData(
                    title=None,
                    meta_description=None,
                    canonical=None,
                    h1_count=0,
                    first_h1=None,
                    word_count=0,
                    meta_robots=None,
                    internal_links=[],
                    external_links=[],
                    content_hash="",
                )

            # Yield the result
            yield (crawl_result, extracted_data, depth)

            pages_crawled += 1

        # Cleanup
        if self.client:
            await self.client.aclose()

    def stop(self) -> None:
        """Stop the crawl."""
        self._stop_flag = True
