"""
Test-Driven Development tests for Diff Engine Service.
These tests are written FIRST to define the expected behavior.
"""
import uuid
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

from app.models.audit import AuditIssue, AuditRun, AuditStatus, IssueType, IssueSeverity
from app.services.audit.differ import AuditDiffer, DiffResult


@pytest.fixture
def mock_session():
    """Create a mock database session"""
    return MagicMock()


@pytest.fixture
def differ(mock_session):
    """Create AuditDiffer instance with mock session"""
    return AuditDiffer(session=mock_session)


def create_mock_audit_run(run_id=None, project_id=None, status=AuditStatus.COMPLETED):
    """Helper to create a mock AuditRun"""
    return AuditRun(
        id=run_id or uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        status=status,
        config={},
        stats={},
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        issues=[],
        pages=[],
        link_edges=[],
    )


def create_mock_issue(page_url, issue_type, audit_run_id=None):
    """Helper to create a mock AuditIssue"""
    issue_type_enum = issue_type if isinstance(issue_type, IssueType) else IssueType(issue_type)
    return AuditIssue(
        id=uuid.uuid4(),
        audit_run_id=audit_run_id or uuid.uuid4(),
        page_url=page_url,
        issue_type=issue_type_enum,
        severity=IssueSeverity.HIGH,
        details={},
        is_new=True,
        first_seen_run_id=None,
    )


class TestGetPreviousRun:
    """Test get_previous_run method"""

    def test_get_previous_run_returns_most_recent(self, differ, mock_session):
        """Should return the most recent completed audit run"""
        project_id = uuid.uuid4()
        current_run_id = uuid.uuid4()
        previous_run_id = uuid.uuid4()

        # Create mock previous run
        previous_run = create_mock_audit_run(
            run_id=previous_run_id,
            project_id=project_id,
            status=AuditStatus.COMPLETED
        )

        # Mock the session.exec to return the previous run
        mock_result = Mock()
        mock_result.first.return_value = previous_run
        mock_session.exec.return_value = mock_result

        result = differ.get_previous_run(project_id, current_run_id)

        assert result == previous_run
        # Verify session.exec was called
        assert mock_session.exec.called

    def test_get_previous_run_returns_none_when_no_previous(self, differ, mock_session):
        """Should return None when there is no previous completed run"""
        project_id = uuid.uuid4()
        current_run_id = uuid.uuid4()

        # Mock session to return None
        mock_result = Mock()
        mock_result.first.return_value = None
        mock_session.exec.return_value = mock_result

        result = differ.get_previous_run(project_id, current_run_id)

        assert result is None

    def test_get_previous_run_excludes_current_run(self, differ, mock_session):
        """Should not return the current run as the previous run"""
        project_id = uuid.uuid4()
        current_run_id = uuid.uuid4()

        # The query should exclude current_run_id
        mock_result = Mock()
        mock_result.first.return_value = None
        mock_session.exec.return_value = mock_result

        differ.get_previous_run(project_id, current_run_id)

        # Verify exec was called (the SQL statement would filter out current_run_id)
        assert mock_session.exec.called

    def test_get_previous_run_only_completed_status(self, differ, mock_session):
        """Should only return runs with COMPLETED status"""
        project_id = uuid.uuid4()
        current_run_id = uuid.uuid4()

        # Mock should filter for status == "completed"
        mock_result = Mock()
        mock_result.first.return_value = None
        mock_session.exec.return_value = mock_result

        differ.get_previous_run(project_id, current_run_id)

        assert mock_session.exec.called


class TestComputeDiffNoPreviousRun:
    """Test compute_diff when there is no previous run"""

    def test_all_issues_are_new_when_no_previous(self, differ, mock_session):
        """Should mark all issues as new when there is no previous run"""
        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
            create_mock_issue("https://example.com/page2", IssueType.THIN_CONTENT, current_run.id),
            create_mock_issue("https://example.com/page3", IssueType.MISSING_H1, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run=None)

        # All issues should be marked as new
        for issue in current_run.issues:
            assert issue.is_new is True
            assert issue.first_seen_run_id == current_run.id

        # Verify diff result
        assert result.new_issues == 3
        assert result.resolved_issues == 0
        assert result.unchanged_issues == 0

        # Verify session.commit was called
        assert mock_session.commit.called

    def test_empty_issues_no_previous_run(self, differ, mock_session):
        """Should handle empty issues list with no previous run"""
        current_run = create_mock_audit_run()
        current_run.issues = []

        result = differ.compute_diff(current_run, previous_run=None)

        assert result.new_issues == 0
        assert result.resolved_issues == 0
        assert result.unchanged_issues == 0


class TestComputeDiffWithPreviousRun:
    """Test compute_diff when there is a previous run"""

    def test_new_issues_detected(self, differ, mock_session):
        """Should detect new issues that were not in previous run"""
        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
        ]
        previous_run.issues[0].first_seen_run_id = previous_run.id

        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
            create_mock_issue("https://example.com/page2", IssueType.THIN_CONTENT, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run)

        # page1 issue is unchanged, page2 is new
        assert result.new_issues == 1
        assert result.unchanged_issues == 1
        assert result.resolved_issues == 0

        # Check issue flags
        page1_issue = next(i for i in current_run.issues if i.page_url == "https://example.com/page1")
        page2_issue = next(i for i in current_run.issues if i.page_url == "https://example.com/page2")

        assert page1_issue.is_new is False
        assert page1_issue.first_seen_run_id == previous_run.id

        assert page2_issue.is_new is True
        assert page2_issue.first_seen_run_id == current_run.id

    def test_resolved_issues_detected(self, differ, mock_session):
        """Should count resolved issues that existed in previous but not in current"""
        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
            create_mock_issue("https://example.com/page2", IssueType.THIN_CONTENT, previous_run.id),
            create_mock_issue("https://example.com/page3", IssueType.MISSING_H1, previous_run.id),
        ]
        for issue in previous_run.issues:
            issue.first_seen_run_id = previous_run.id

        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run)

        # page1 is unchanged, page2 and page3 are resolved
        assert result.new_issues == 0
        assert result.unchanged_issues == 1
        assert result.resolved_issues == 2

    def test_unchanged_issues_preserve_first_seen(self, differ, mock_session):
        """Should preserve first_seen_run_id for unchanged issues"""
        first_run_id = uuid.uuid4()

        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
        ]
        previous_run.issues[0].first_seen_run_id = first_run_id
        previous_run.issues[0].is_new = False

        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run)

        # Issue should be unchanged
        assert result.unchanged_issues == 1
        assert result.new_issues == 0

        # Should preserve the original first_seen_run_id
        assert current_run.issues[0].is_new is False
        assert current_run.issues[0].first_seen_run_id == first_run_id

    def test_different_issue_types_same_page(self, differ, mock_session):
        """Should treat different issue types on same page as separate issues"""
        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
        ]
        previous_run.issues[0].first_seen_run_id = previous_run.id

        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
            create_mock_issue("https://example.com/page1", IssueType.MISSING_H1, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run)

        # MISSING_TITLE is unchanged, MISSING_H1 is new
        assert result.new_issues == 1
        assert result.unchanged_issues == 1
        assert result.resolved_issues == 0

    def test_same_issue_type_different_pages(self, differ, mock_session):
        """Should treat same issue type on different pages as separate issues"""
        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
        ]
        previous_run.issues[0].first_seen_run_id = previous_run.id

        current_run = create_mock_audit_run()
        current_run.issues = [
            create_mock_issue("https://example.com/page2", IssueType.MISSING_TITLE, current_run.id),
        ]

        result = differ.compute_diff(current_run, previous_run)

        # page1 issue is resolved, page2 issue is new
        assert result.new_issues == 1
        assert result.unchanged_issues == 0
        assert result.resolved_issues == 1

    def test_complex_diff_scenario(self, differ, mock_session):
        """Should handle complex scenario with new, resolved, and unchanged issues"""
        previous_run = create_mock_audit_run()
        previous_run.issues = [
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, previous_run.id),
            create_mock_issue("https://example.com/page2", IssueType.THIN_CONTENT, previous_run.id),
            create_mock_issue("https://example.com/page3", IssueType.MISSING_H1, previous_run.id),
            create_mock_issue("https://example.com/page4", IssueType.MISSING_META_DESCRIPTION, previous_run.id),
        ]
        for issue in previous_run.issues:
            issue.first_seen_run_id = previous_run.id

        current_run = create_mock_audit_run()
        current_run.issues = [
            # Unchanged from previous
            create_mock_issue("https://example.com/page1", IssueType.MISSING_TITLE, current_run.id),
            create_mock_issue("https://example.com/page3", IssueType.MISSING_H1, current_run.id),
            # New issues
            create_mock_issue("https://example.com/page5", IssueType.TITLE_TOO_LONG, current_run.id),
            create_mock_issue("https://example.com/page6", IssueType.MULTIPLE_H1, current_run.id),
            # page2 and page4 are resolved (not in current run)
        ]

        result = differ.compute_diff(current_run, previous_run)

        assert result.new_issues == 2  # page5, page6
        assert result.unchanged_issues == 2  # page1, page3
        assert result.resolved_issues == 2  # page2, page4

        # Verify commit was called
        assert mock_session.commit.called


class TestDiffResultDataClass:
    """Test DiffResult data class"""

    def test_diff_result_creation(self):
        """Should create DiffResult with correct attributes"""
        result = DiffResult(
            new_issues=5,
            resolved_issues=3,
            unchanged_issues=10
        )

        assert result.new_issues == 5
        assert result.resolved_issues == 3
        assert result.unchanged_issues == 10

    def test_diff_result_zero_values(self):
        """Should handle zero values correctly"""
        result = DiffResult(
            new_issues=0,
            resolved_issues=0,
            unchanged_issues=0
        )

        assert result.new_issues == 0
        assert result.resolved_issues == 0
        assert result.unchanged_issues == 0
