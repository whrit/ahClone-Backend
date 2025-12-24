"""
Diff Engine Service
Compares audit runs to track new/resolved issues.
"""
import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.audit import AuditIssue, AuditRun, IssueType


@dataclass
class DiffResult:
    """Result of comparing two audit runs"""
    new_issues: int
    resolved_issues: int
    unchanged_issues: int


class AuditDiffer:
    """Compare audit runs to track new/resolved issues"""

    def __init__(self, session: Session):
        """
        Initialize the differ.

        Args:
            session: SQLModel database session
        """
        self.session = session

    def get_previous_run(
        self, project_id: uuid.UUID, current_run_id: uuid.UUID
    ) -> AuditRun | None:
        """
        Get the most recent completed audit run before the current one.

        Args:
            project_id: The project ID
            current_run_id: The current run ID to exclude

        Returns:
            The previous AuditRun or None if no previous run exists
        """
        from sqlmodel import col

        statement = (
            select(AuditRun)
            .where(AuditRun.project_id == project_id)
            .where(AuditRun.id != current_run_id)
            .where(AuditRun.status == "completed")
            .order_by(col(AuditRun.finished_at).desc())
            .limit(1)
        )
        return self.session.exec(statement).first()

    def compute_diff(
        self, current_run: AuditRun, previous_run: AuditRun | None
    ) -> DiffResult:
        """
        Compare current run issues with previous run.
        Updates is_new and first_seen_run_id on current issues.

        Args:
            current_run: The current audit run with issues
            previous_run: The previous audit run to compare against (or None)

        Returns:
            DiffResult with counts of new, resolved, and unchanged issues
        """
        if not previous_run:
            # First run - all issues are new
            for issue in current_run.issues:
                issue.is_new = True
                issue.first_seen_run_id = current_run.id
            self.session.commit()
            return DiffResult(
                new_issues=len(current_run.issues),
                resolved_issues=0,
                unchanged_issues=0,
            )

        # Build lookup of previous issues by (page_url, issue_type)
        previous_issues: dict[tuple[str, IssueType], AuditIssue] = {}
        for issue in previous_run.issues:
            key = (issue.page_url, issue.issue_type)
            previous_issues[key] = issue

        new_count = 0
        unchanged_count = 0

        # Compare current issues
        for issue in current_run.issues:
            key = (issue.page_url, issue.issue_type)
            if key in previous_issues:
                # Issue existed before - mark as unchanged
                issue.is_new = False
                issue.first_seen_run_id = previous_issues[key].first_seen_run_id
                unchanged_count += 1
                # Remove from previous_issues lookup
                del previous_issues[key]
            else:
                # New issue
                issue.is_new = True
                issue.first_seen_run_id = current_run.id
                new_count += 1

        # Remaining in previous_issues are resolved
        resolved_count = len(previous_issues)

        self.session.commit()

        return DiffResult(
            new_issues=new_count,
            resolved_issues=resolved_count,
            unchanged_issues=unchanged_count,
        )
