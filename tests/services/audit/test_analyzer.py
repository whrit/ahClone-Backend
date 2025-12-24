"""
Test-Driven Development tests for Issue Analyzer Service.
These tests are written FIRST to define the expected behavior.
"""
import uuid
from datetime import datetime

import pytest

from app.models.audit import CrawledPage, IssueType, IssueSeverity
from app.services.audit.analyzer import DetectedIssue, DuplicateDetector, IssueAnalyzer


@pytest.fixture
def https_analyzer():
    """Analyzer for HTTPS seed URL"""
    return IssueAnalyzer(seed_url="https://example.com")


@pytest.fixture
def http_analyzer():
    """Analyzer for HTTP seed URL"""
    return IssueAnalyzer(seed_url="http://example.com")


def create_mock_page(**kwargs):
    """Helper to create a mock CrawledPage with default values"""
    defaults = {
        "id": uuid.uuid4(),
        "audit_run_id": uuid.uuid4(),
        "url": "https://example.com/page",
        "final_url": "https://example.com/page",
        "depth": 0,
        "status_code": 200,
        "content_type": "text/html",
        "response_time_ms": 100,
        "redirect_chain": [],
        "title": "Valid Page Title",
        "meta_description": "This is a valid meta description that is long enough to pass validation",
        "canonical": "https://example.com/page",
        "h1_count": 1,
        "first_h1": "Main Heading",
        "word_count": 500,
        "meta_robots": None,
        "is_rendered": False,
        "rendered_at": None,
        "rendered_title": None,
        "rendered_meta_description": None,
        "rendered_h1_count": None,
        "rendered_word_count": None,
        "content_hash": "abc123",
        "crawled_at": datetime.utcnow(),
    }
    defaults.update(kwargs)
    return CrawledPage(**defaults)


class TestIssueAnalyzerStatusCodes:
    """Test status code detection rules"""

    def test_detect_5xx_error(self, https_analyzer):
        """Should detect SERVER_ERROR_5XX for 5xx status codes"""
        page = create_mock_page(status_code=500)
        issues = list(https_analyzer.analyze_page(page))

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.SERVER_ERROR_5XX
        assert issues[0].severity == IssueSeverity.CRITICAL
        assert issues[0].page_url == page.url
        assert issues[0].details["status_code"] == 500

    def test_detect_503_error(self, https_analyzer):
        """Should detect SERVER_ERROR_5XX for 503 status code"""
        page = create_mock_page(status_code=503)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.SERVER_ERROR_5XX for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.SERVER_ERROR_5XX)
        assert issue.details["status_code"] == 503

    def test_detect_4xx_error(self, https_analyzer):
        """Should detect CLIENT_ERROR_4XX for 4xx status codes"""
        page = create_mock_page(status_code=404)
        issues = list(https_analyzer.analyze_page(page))

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.CLIENT_ERROR_4XX
        assert issues[0].severity == IssueSeverity.HIGH
        assert issues[0].details["status_code"] == 404

    def test_detect_403_error(self, https_analyzer):
        """Should detect CLIENT_ERROR_4XX for 403 status code"""
        page = create_mock_page(status_code=403)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.CLIENT_ERROR_4XX for i in issues)

    def test_no_error_for_200(self, https_analyzer):
        """Should not detect status code errors for 200 OK"""
        page = create_mock_page(status_code=200)
        issues = list(https_analyzer.analyze_page(page))

        # Should have no status code related issues
        assert not any(
            i.issue_type in [IssueType.SERVER_ERROR_5XX, IssueType.CLIENT_ERROR_4XX]
            for i in issues
        )


class TestIssueAnalyzerRedirects:
    """Test redirect detection rules"""

    def test_detect_redirect_chain(self, https_analyzer):
        """Should detect REDIRECT_CHAIN when chain exceeds threshold"""
        page = create_mock_page(
            redirect_chain=[
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
                "https://example.com/d",
            ]
        )
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.REDIRECT_CHAIN for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.REDIRECT_CHAIN)
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.details["chain_length"] == 4
        assert "chain" in issue.details

    def test_no_redirect_chain_for_short_chain(self, https_analyzer):
        """Should not detect REDIRECT_CHAIN for chains <= 3"""
        page = create_mock_page(
            redirect_chain=[
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ]
        )
        issues = list(https_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.REDIRECT_CHAIN for i in issues)

    def test_detect_redirect_loop_url_in_chain(self, https_analyzer):
        """Should detect REDIRECT_LOOP when URL appears in its own chain"""
        page = create_mock_page(
            url="https://example.com/a",
            redirect_chain=[
                "https://example.com/b",
                "https://example.com/a",
                "https://example.com/c",
            ]
        )
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.REDIRECT_LOOP for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.REDIRECT_LOOP)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_detect_redirect_loop_final_in_chain(self, https_analyzer):
        """Should detect REDIRECT_LOOP when final_url appears in middle of chain"""
        page = create_mock_page(
            final_url="https://example.com/z",
            redirect_chain=[
                "https://example.com/a",
                "https://example.com/z",
                "https://example.com/b",
            ]
        )
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.REDIRECT_LOOP for i in issues)


class TestIssueAnalyzerTitle:
    """Test title detection rules"""

    def test_detect_missing_title(self, https_analyzer):
        """Should detect MISSING_TITLE when title is None"""
        page = create_mock_page(title=None)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MISSING_TITLE for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.MISSING_TITLE)
        assert issue.severity == IssueSeverity.HIGH

    def test_detect_missing_title_empty_string(self, https_analyzer):
        """Should detect MISSING_TITLE when title is empty string"""
        page = create_mock_page(title="")
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MISSING_TITLE for i in issues)

    def test_detect_title_too_short(self, https_analyzer):
        """Should detect TITLE_TOO_SHORT when title < 10 chars"""
        page = create_mock_page(title="Short")
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.TITLE_TOO_SHORT for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.TITLE_TOO_SHORT)
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.details["length"] == 5
        assert issue.details["title"] == "Short"

    def test_detect_title_too_long(self, https_analyzer):
        """Should detect TITLE_TOO_LONG when title > 60 chars"""
        long_title = "This is a very long title that exceeds the sixty character limit for SEO"
        page = create_mock_page(title=long_title)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.TITLE_TOO_LONG for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.TITLE_TOO_LONG)
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.details["length"] == len(long_title)

    def test_valid_title_no_issues(self, https_analyzer):
        """Should not detect title issues for valid title (10-60 chars)"""
        page = create_mock_page(title="Valid Page Title")
        issues = list(https_analyzer.analyze_page(page))

        title_issues = [
            i for i in issues
            if i.issue_type in [
                IssueType.MISSING_TITLE,
                IssueType.TITLE_TOO_SHORT,
                IssueType.TITLE_TOO_LONG,
            ]
        ]
        assert len(title_issues) == 0


class TestIssueAnalyzerMetaDescription:
    """Test meta description detection rules"""

    def test_detect_missing_meta_description(self, https_analyzer):
        """Should detect MISSING_META_DESCRIPTION when meta_description is None"""
        page = create_mock_page(meta_description=None)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MISSING_META_DESCRIPTION for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.MISSING_META_DESCRIPTION)
        assert issue.severity == IssueSeverity.HIGH

    def test_detect_meta_desc_too_short(self, https_analyzer):
        """Should detect META_DESC_TOO_SHORT when meta_description < 50 chars"""
        page = create_mock_page(meta_description="Short description")
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.META_DESC_TOO_SHORT for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.META_DESC_TOO_SHORT)
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.details["length"] < 50

    def test_detect_meta_desc_too_long(self, https_analyzer):
        """Should detect META_DESC_TOO_LONG when meta_description > 160 chars"""
        long_desc = "This is a very long meta description that exceeds the one hundred sixty character limit and should be detected as too long for optimal SEO performance in search results"
        page = create_mock_page(meta_description=long_desc)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.META_DESC_TOO_LONG for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.META_DESC_TOO_LONG)
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.details["length"] > 160

    def test_valid_meta_description_no_issues(self, https_analyzer):
        """Should not detect meta description issues for valid length (50-160 chars)"""
        page = create_mock_page(
            meta_description="This is a valid meta description that is long enough to pass validation"
        )
        issues = list(https_analyzer.analyze_page(page))

        meta_issues = [
            i for i in issues
            if i.issue_type in [
                IssueType.MISSING_META_DESCRIPTION,
                IssueType.META_DESC_TOO_SHORT,
                IssueType.META_DESC_TOO_LONG,
            ]
        ]
        assert len(meta_issues) == 0


class TestIssueAnalyzerH1:
    """Test H1 detection rules"""

    def test_detect_missing_h1(self, https_analyzer):
        """Should detect MISSING_H1 when h1_count is 0"""
        page = create_mock_page(h1_count=0)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MISSING_H1 for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.MISSING_H1)
        assert issue.severity == IssueSeverity.MEDIUM

    def test_detect_multiple_h1(self, https_analyzer):
        """Should detect MULTIPLE_H1 when h1_count > 1"""
        page = create_mock_page(h1_count=3)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MULTIPLE_H1 for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.MULTIPLE_H1)
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.details["count"] == 3

    def test_valid_h1_count_no_issues(self, https_analyzer):
        """Should not detect H1 issues when h1_count is exactly 1"""
        page = create_mock_page(h1_count=1)
        issues = list(https_analyzer.analyze_page(page))

        h1_issues = [
            i for i in issues
            if i.issue_type in [IssueType.MISSING_H1, IssueType.MULTIPLE_H1]
        ]
        assert len(h1_issues) == 0


class TestIssueAnalyzerCanonical:
    """Test canonical URL detection rules"""

    def test_detect_missing_canonical(self, https_analyzer):
        """Should detect MISSING_CANONICAL when canonical is None"""
        page = create_mock_page(canonical=None)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.MISSING_CANONICAL for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.MISSING_CANONICAL)
        assert issue.severity == IssueSeverity.MEDIUM

    def test_detect_canonical_mismatch_different_domain(self, https_analyzer):
        """Should detect CANONICAL_MISMATCH when canonical points to different domain"""
        page = create_mock_page(
            url="https://example.com/page",
            final_url="https://example.com/page",
            canonical="https://different.com/page"
        )
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.CANONICAL_MISMATCH for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.CANONICAL_MISMATCH)
        assert issue.severity == IssueSeverity.MEDIUM
        assert "canonical" in issue.details
        assert "page_url" in issue.details

    def test_no_canonical_mismatch_same_url(self, https_analyzer):
        """Should not detect mismatch when canonical matches page URL"""
        page = create_mock_page(
            url="https://example.com/page",
            final_url="https://example.com/page",
            canonical="https://example.com/page"
        )
        issues = list(https_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.CANONICAL_MISMATCH for i in issues)

    def test_no_canonical_mismatch_same_domain(self, https_analyzer):
        """Should not detect mismatch when canonical is same domain but different path"""
        page = create_mock_page(
            url="https://example.com/page",
            final_url="https://example.com/page",
            canonical="https://example.com/other-page"
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should not be a mismatch - same domain, just different path
        assert not any(i.issue_type == IssueType.CANONICAL_MISMATCH for i in issues)


class TestIssueAnalyzerHTTPS:
    """Test HTTPS detection rules"""

    def test_detect_non_https_when_seed_is_https(self, https_analyzer):
        """Should detect NON_HTTPS when seed is HTTPS but page is HTTP"""
        page = create_mock_page(
            url="http://example.com/page",
            final_url="http://example.com/page"
        )
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.NON_HTTPS for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.NON_HTTPS)
        assert issue.severity == IssueSeverity.MEDIUM
        assert "final_url" in issue.details

    def test_no_https_issue_when_seed_is_http(self, http_analyzer):
        """Should not detect NON_HTTPS when seed URL is HTTP"""
        page = create_mock_page(
            url="http://example.com/page",
            final_url="http://example.com/page"
        )
        issues = list(http_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.NON_HTTPS for i in issues)

    def test_no_https_issue_when_both_https(self, https_analyzer):
        """Should not detect NON_HTTPS when both seed and page are HTTPS"""
        page = create_mock_page(
            url="https://example.com/page",
            final_url="https://example.com/page"
        )
        issues = list(https_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.NON_HTTPS for i in issues)


class TestIssueAnalyzerThinContent:
    """Test thin content detection rules"""

    def test_detect_thin_content(self, https_analyzer):
        """Should detect THIN_CONTENT when word_count < 300"""
        page = create_mock_page(word_count=150)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.THIN_CONTENT for i in issues)
        issue = next(i for i in issues if i.issue_type == IssueType.THIN_CONTENT)
        assert issue.severity == IssueSeverity.LOW
        assert issue.details["word_count"] == 150

    def test_no_thin_content_for_sufficient_words(self, https_analyzer):
        """Should not detect THIN_CONTENT when word_count >= 300"""
        page = create_mock_page(word_count=500)
        issues = list(https_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.THIN_CONTENT for i in issues)

    def test_thin_content_boundary_299(self, https_analyzer):
        """Should detect THIN_CONTENT at boundary value 299"""
        page = create_mock_page(word_count=299)
        issues = list(https_analyzer.analyze_page(page))

        assert any(i.issue_type == IssueType.THIN_CONTENT for i in issues)

    def test_no_thin_content_boundary_300(self, https_analyzer):
        """Should not detect THIN_CONTENT at boundary value 300"""
        page = create_mock_page(word_count=300)
        issues = list(https_analyzer.analyze_page(page))

        assert not any(i.issue_type == IssueType.THIN_CONTENT for i in issues)


class TestIssueAnalyzerRenderedContent:
    """Test that analyzer uses rendered values when available"""

    def test_use_rendered_title_when_available(self, https_analyzer):
        """Should use rendered_title instead of title when is_rendered is True"""
        page = create_mock_page(
            title="HTML Title Too Short",
            rendered_title="This is the rendered title from JavaScript that is valid",
            is_rendered=True
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should not detect title too short because rendered title is valid
        assert not any(i.issue_type == IssueType.TITLE_TOO_SHORT for i in issues)

    def test_use_rendered_meta_description_when_available(self, https_analyzer):
        """Should use rendered_meta_description when is_rendered is True"""
        page = create_mock_page(
            meta_description="Short",
            rendered_meta_description="This is a valid rendered meta description that is long enough",
            is_rendered=True
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should not detect meta desc too short because rendered desc is valid
        assert not any(i.issue_type == IssueType.META_DESC_TOO_SHORT for i in issues)

    def test_use_rendered_h1_count_when_available(self, https_analyzer):
        """Should use rendered_h1_count when is_rendered is True"""
        page = create_mock_page(
            h1_count=0,
            rendered_h1_count=1,
            is_rendered=True
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should not detect missing H1 because rendered h1 count is 1
        assert not any(i.issue_type == IssueType.MISSING_H1 for i in issues)

    def test_use_rendered_word_count_when_available(self, https_analyzer):
        """Should use rendered_word_count when is_rendered is True"""
        page = create_mock_page(
            word_count=100,
            rendered_word_count=500,
            is_rendered=True
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should not detect thin content because rendered word count is 500
        assert not any(i.issue_type == IssueType.THIN_CONTENT for i in issues)

    def test_fallback_to_html_when_not_rendered(self, https_analyzer):
        """Should use HTML values when is_rendered is False"""
        page = create_mock_page(
            word_count=100,
            rendered_word_count=500,
            is_rendered=False
        )
        issues = list(https_analyzer.analyze_page(page))

        # Should detect thin content because using HTML word count (100)
        assert any(i.issue_type == IssueType.THIN_CONTENT for i in issues)


class TestDuplicateDetector:
    """Test duplicate title detection"""

    def test_detect_duplicate_titles(self):
        """Should detect when multiple pages have the same title"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", "Same Title", "hash1")
        detector.add_page("https://example.com/page2", "Same Title", "hash2")
        detector.add_page("https://example.com/page3", "Different Title", "hash3")

        issues = list(detector.get_duplicate_title_issues())

        # Should have 2 issues (one for each URL with "Same Title")
        assert len(issues) == 2
        duplicate_urls = {issue.page_url for issue in issues}
        assert "https://example.com/page1" in duplicate_urls
        assert "https://example.com/page2" in duplicate_urls

        # Check issue details
        for issue in issues:
            assert issue.issue_type == IssueType.DUPLICATE_TITLE
            assert issue.severity == IssueSeverity.HIGH
            assert "duplicate_urls" in issue.details

    def test_no_duplicates_for_unique_titles(self):
        """Should not detect duplicates when all titles are unique"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", "Title One", "hash1")
        detector.add_page("https://example.com/page2", "Title Two", "hash2")
        detector.add_page("https://example.com/page3", "Title Three", "hash3")

        issues = list(detector.get_duplicate_title_issues())

        assert len(issues) == 0

    def test_ignore_none_titles(self):
        """Should ignore pages with None titles"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", None, "hash1")
        detector.add_page("https://example.com/page2", None, "hash2")

        issues = list(detector.get_duplicate_title_issues())

        # Should not consider None titles as duplicates
        assert len(issues) == 0

    def test_case_insensitive_duplicate_detection(self):
        """Should detect duplicates case-insensitively"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", "Same Title", "hash1")
        detector.add_page("https://example.com/page2", "SAME TITLE", "hash2")
        detector.add_page("https://example.com/page3", "same title", "hash3")

        issues = list(detector.get_duplicate_title_issues())

        # All three should be considered duplicates
        assert len(issues) == 3

    def test_trim_whitespace_in_titles(self):
        """Should trim whitespace when comparing titles"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", "  Same Title  ", "hash1")
        detector.add_page("https://example.com/page2", "Same Title", "hash2")

        issues = list(detector.get_duplicate_title_issues())

        # Should detect as duplicates after trimming
        assert len(issues) == 2

    def test_duplicate_details_exclude_self(self):
        """duplicate_urls in details should exclude the current URL"""
        detector = DuplicateDetector()

        detector.add_page("https://example.com/page1", "Same Title", "hash1")
        detector.add_page("https://example.com/page2", "Same Title", "hash2")

        issues = list(detector.get_duplicate_title_issues())

        for issue in issues:
            # The duplicate_urls list should not contain the current page URL
            assert issue.page_url not in issue.details["duplicate_urls"]
            # But should contain the other URL(s)
            assert len(issue.details["duplicate_urls"]) == 1


class TestIssueAnalyzerConstants:
    """Test that analyzer has correct constants"""

    def test_constants_defined(self):
        """Should have all required threshold constants"""
        assert IssueAnalyzer.TITLE_MIN_LENGTH == 10
        assert IssueAnalyzer.TITLE_MAX_LENGTH == 60
        assert IssueAnalyzer.META_DESC_MIN_LENGTH == 50
        assert IssueAnalyzer.META_DESC_MAX_LENGTH == 160
        assert IssueAnalyzer.THIN_CONTENT_THRESHOLD == 300
        assert IssueAnalyzer.REDIRECT_CHAIN_MAX == 3
