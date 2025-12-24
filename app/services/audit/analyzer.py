"""
Issue Analyzer Service
Analyzes crawled pages and detects SEO issues.
"""
from dataclasses import dataclass
from typing import Any, Generator
from urllib.parse import urlparse

from app.models.audit import CrawledPage, IssueSeverity, IssueType, ISSUE_SEVERITY_MAP


@dataclass
class DetectedIssue:
    """Represents a detected SEO issue"""
    page_url: str
    issue_type: IssueType
    severity: IssueSeverity
    details: dict[str, Any]


class IssueAnalyzer:
    """Analyze crawled pages and detect SEO issues"""

    # Configurable thresholds
    TITLE_MIN_LENGTH = 10
    TITLE_MAX_LENGTH = 60
    META_DESC_MIN_LENGTH = 50
    META_DESC_MAX_LENGTH = 160
    THIN_CONTENT_THRESHOLD = 300
    REDIRECT_CHAIN_MAX = 3

    def __init__(self, seed_url: str):
        """
        Initialize the analyzer.

        Args:
            seed_url: The seed URL of the project being analyzed
        """
        self.seed_url = seed_url
        self.seed_is_https = seed_url.startswith("https://")

    def analyze_page(self, page: CrawledPage) -> Generator[DetectedIssue, None, None]:
        """
        Analyze a single page and yield detected issues.

        Args:
            page: CrawledPage object to analyze

        Yields:
            DetectedIssue objects for each issue found
        """
        # Status code issues (return early if error - don't analyze further)
        if 500 <= page.status_code < 600:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.SERVER_ERROR_5XX,
                severity=IssueSeverity.CRITICAL,
                details={"status_code": page.status_code},
            )
            return  # Don't analyze error pages further

        if 400 <= page.status_code < 500:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.CLIENT_ERROR_4XX,
                severity=IssueSeverity.HIGH,
                details={"status_code": page.status_code},
            )
            return  # Don't analyze error pages further

        # Redirect issues
        if page.redirect_chain:
            # Convert redirect_chain to list of strings for checking
            redirect_urls = []
            for item in page.redirect_chain:
                if isinstance(item, dict):
                    redirect_urls.append(str(item.get("url", "")))
                elif isinstance(item, str):
                    redirect_urls.append(item)

            # Check for redirect chain length
            if len(redirect_urls) > self.REDIRECT_CHAIN_MAX:
                yield DetectedIssue(
                    page_url=page.url,
                    issue_type=IssueType.REDIRECT_CHAIN,
                    severity=ISSUE_SEVERITY_MAP[IssueType.REDIRECT_CHAIN],
                    details={
                        "chain_length": len(redirect_urls),
                        "chain": redirect_urls,
                    },
                )

            # Check for redirect loops
            # URL appears in chain OR final_url appears in middle of chain
            if page.url in redirect_urls or (
                page.final_url in redirect_urls[:-1]
                if len(redirect_urls) > 1
                else False
            ):
                yield DetectedIssue(
                    page_url=page.url,
                    issue_type=IssueType.REDIRECT_LOOP,
                    severity=IssueSeverity.CRITICAL,
                    details={"chain": redirect_urls},
                )

        # Use rendered values if available, otherwise HTML values
        title = page.rendered_title if page.is_rendered else page.title
        meta_desc = (
            page.rendered_meta_description
            if page.is_rendered
            else page.meta_description
        )
        h1_count = (
            page.rendered_h1_count
            if page.is_rendered and page.rendered_h1_count is not None
            else (page.h1_count if page.h1_count is not None else 0)
        )
        word_count = (
            page.rendered_word_count
            if page.is_rendered and page.rendered_word_count is not None
            else (page.word_count if page.word_count is not None else 0)
        )

        # Title issues
        if not title:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.MISSING_TITLE,
                severity=IssueSeverity.HIGH,
                details={},
            )
        elif len(title) < self.TITLE_MIN_LENGTH:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.TITLE_TOO_SHORT,
                severity=ISSUE_SEVERITY_MAP[IssueType.TITLE_TOO_SHORT],
                details={"length": len(title), "title": title},
            )
        elif len(title) > self.TITLE_MAX_LENGTH:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.TITLE_TOO_LONG,
                severity=ISSUE_SEVERITY_MAP[IssueType.TITLE_TOO_LONG],
                details={"length": len(title), "title": title},
            )

        # Meta description issues
        if not meta_desc:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.MISSING_META_DESCRIPTION,
                severity=IssueSeverity.HIGH,
                details={},
            )
        elif len(meta_desc) < self.META_DESC_MIN_LENGTH:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.META_DESC_TOO_SHORT,
                severity=ISSUE_SEVERITY_MAP[IssueType.META_DESC_TOO_SHORT],
                details={"length": len(meta_desc)},
            )
        elif len(meta_desc) > self.META_DESC_MAX_LENGTH:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.META_DESC_TOO_LONG,
                severity=ISSUE_SEVERITY_MAP[IssueType.META_DESC_TOO_LONG],
                details={"length": len(meta_desc)},
            )

        # H1 issues
        if h1_count == 0:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.MISSING_H1,
                severity=IssueSeverity.MEDIUM,
                details={},
            )
        elif h1_count > 1:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.MULTIPLE_H1,
                severity=IssueSeverity.MEDIUM,
                details={"count": h1_count},
            )

        # Canonical issues
        if not page.canonical:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.MISSING_CANONICAL,
                severity=IssueSeverity.MEDIUM,
                details={},
            )
        elif page.canonical != page.final_url and page.canonical != page.url:
            # Check if canonical points to different domain
            canonical_domain = urlparse(page.canonical).netloc
            page_domain = urlparse(page.final_url).netloc
            if canonical_domain != page_domain:
                yield DetectedIssue(
                    page_url=page.url,
                    issue_type=IssueType.CANONICAL_MISMATCH,
                    severity=IssueSeverity.MEDIUM,
                    details={"canonical": page.canonical, "page_url": page.final_url},
                )

        # HTTPS issues
        if self.seed_is_https and not page.final_url.startswith("https://"):
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.NON_HTTPS,
                severity=ISSUE_SEVERITY_MAP[IssueType.NON_HTTPS],
                details={"final_url": page.final_url},
            )

        # Thin content
        if word_count < self.THIN_CONTENT_THRESHOLD:
            yield DetectedIssue(
                page_url=page.url,
                issue_type=IssueType.THIN_CONTENT,
                severity=ISSUE_SEVERITY_MAP[IssueType.THIN_CONTENT],
                details={"word_count": word_count},
            )


class DuplicateDetector:
    """Detect duplicate titles and content across pages"""

    def __init__(self) -> None:
        """Initialize the duplicate detector"""
        self.titles: dict[str, list[str]] = {}  # normalized_title -> [urls]
        self.content_hashes: dict[str, list[str]] = {}  # hash -> [urls]

    def add_page(self, url: str, title: str | None, content_hash: str | None) -> None:
        """
        Register a page for duplicate detection.

        Args:
            url: The page URL
            title: The page title (will be normalized)
            content_hash: The content hash for duplicate content detection
        """
        if title:
            normalized = title.strip().lower()
            if normalized not in self.titles:
                self.titles[normalized] = []
            self.titles[normalized].append(url)

        if content_hash:
            if content_hash not in self.content_hashes:
                self.content_hashes[content_hash] = []
            self.content_hashes[content_hash].append(url)

    def get_duplicate_title_issues(self) -> Generator[DetectedIssue, None, None]:
        """
        Yield issues for duplicate titles.

        Yields:
            DetectedIssue objects for each page with a duplicate title
        """
        for title, urls in self.titles.items():
            if len(urls) > 1:
                # Create an issue for each URL with this duplicate title
                for url in urls:
                    yield DetectedIssue(
                        page_url=url,
                        issue_type=IssueType.DUPLICATE_TITLE,
                        severity=IssueSeverity.HIGH,
                        details={
                            "title": title,
                            "duplicate_urls": [u for u in urls if u != url],
                        },
                    )
