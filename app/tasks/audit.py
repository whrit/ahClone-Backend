"""
Celery tasks for SEO audit workflow.

This module implements the audit pipeline:
1. crawl_pages: Crawl website and extract data
2. render_pages: Render JS-heavy pages
3. analyze_pages: Detect SEO issues
4. compute_diff: Compare with previous audit
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from celery import chain, shared_task
from sqlmodel import Session, select

from app.core.db import engine
from app.models.audit import (
    AuditIssue,
    AuditLinkEdge,
    AuditRun,
    AuditStatus,
    CrawledPage,
)
from app.models.project import Project
from app.services.audit.analyzer import DuplicateDetector, IssueAnalyzer
from app.services.audit.crawler import Crawler
from app.services.audit.differ import AuditDiffer
from app.services.audit.renderer import Renderer

if TYPE_CHECKING:
    from celery import Task


@shared_task(name="app.tasks.audit.run_audit")  # type: ignore[misc]
def run_audit(project_id: str, audit_run_id: str) -> dict[str, Any]:
    """
    Main orchestrator task that chains all audit subtasks.

    Args:
        project_id: UUID of the project
        audit_run_id: UUID of the audit run

    Returns:
        Dict with final results from compute_diff
    """
    # Create a chain of tasks
    task_chain = chain(
        crawl_pages.s(project_id, audit_run_id),
        render_pages.s(project_id, audit_run_id),
        analyze_pages.s(project_id, audit_run_id),
        compute_diff.s(project_id, audit_run_id),
    )

    # Execute the chain
    result = task_chain.apply_async()

    return {"chain_id": str(result.id)}


@shared_task(name="app.tasks.audit.crawl_pages", bind=True)  # type: ignore[misc]
def crawl_pages(self: "Task", project_id: str, audit_run_id: str) -> dict[str, Any]:  # noqa: ARG001
    """
    Crawl website pages and extract SEO data.

    Args:
        self: Task instance (bound)
        project_id: UUID of the project
        audit_run_id: UUID of the audit run

    Returns:
        Dict with pages_crawled count
    """
    with Session(engine) as session:
        try:
            # Get audit run and project
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if not audit_run:
                raise ValueError(f"AuditRun {audit_run_id} not found")

            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Update status to CRAWLING
            audit_run.status = AuditStatus.CRAWLING
            audit_run.started_at = datetime.now(timezone.utc)
            session.add(audit_run)
            session.commit()

            # Initialize crawler with config from audit_run
            config = audit_run.config
            crawler = Crawler(
                seed_url=project.seed_url,
                max_pages=config.get("max_pages", 1000),
                max_depth=config.get("max_depth", 10),
                concurrency=config.get("crawl_concurrency", 5),
                user_agent=config.get("user_agent", "SEOPlatformBot/1.0"),
                respect_robots=config.get("respect_robots_txt", True),
                include_patterns=config.get("include_patterns", []),
                exclude_patterns=config.get("exclude_patterns", []),
            )

            # Setup crawler
            asyncio.run(crawler.setup())

            # Crawl pages
            pages_crawled = 0
            total_response_time = 0

            async def run_crawl() -> None:
                nonlocal pages_crawled, total_response_time
                assert audit_run is not None
                async for crawl_result, extracted_data, depth in crawler.crawl():
                    # Create CrawledPage record
                    page = CrawledPage(
                        audit_run_id=audit_run.id,
                        url=crawl_result.url,
                        final_url=crawl_result.final_url or crawl_result.url,
                        depth=depth,
                        status_code=crawl_result.status_code or 0,
                        content_type=crawl_result.content_type,
                        response_time_ms=int(crawl_result.response_time_ms),
                        redirect_chain=[
                            {"url": url} for url in crawl_result.redirect_chain
                        ]
                        if crawl_result.redirect_chain
                        else None,
                        title=extracted_data.title,
                        meta_description=extracted_data.meta_description,
                        canonical=extracted_data.canonical,
                        h1_count=extracted_data.h1_count,
                        first_h1=extracted_data.first_h1,
                        word_count=extracted_data.word_count,
                        meta_robots=extracted_data.meta_robots,
                        content_hash=extracted_data.content_hash,
                        crawled_at=datetime.now(timezone.utc),
                    )
                    session.add(page)

                    # Create AuditLinkEdge records for internal links
                    for link in extracted_data.internal_links:
                        assert audit_run is not None
                        edge = AuditLinkEdge(
                            audit_run_id=audit_run.id,
                            source_url=crawl_result.url,
                            target_url=link,
                            is_internal=True,
                            is_followed=True,
                        )
                        session.add(edge)

                    pages_crawled += 1
                    if crawl_result.response_time_ms:
                        total_response_time += int(crawl_result.response_time_ms)

                    # Update progress every 10 pages
                    if pages_crawled % 10 == 0:
                        assert audit_run is not None
                        session.commit()
                        # Calculate progress
                        audit_run.progress_pct = min(20.0, (pages_crawled / config.get("max_pages", 1000)) * 20)
                        audit_run.progress_message = f"Crawled {pages_crawled} pages"
                        session.add(audit_run)
                        session.commit()

            # Run the crawl
            asyncio.run(run_crawl())

            # Final commit
            session.commit()

            # Update stats
            avg_response_time = (
                int(total_response_time / pages_crawled) if pages_crawled > 0 else 0
            )

            # Get page counts by status
            pages_ok = session.exec(
                select(CrawledPage).where(
                    CrawledPage.audit_run_id == audit_run.id,
                    CrawledPage.status_code >= 200,
                    CrawledPage.status_code < 300,
                )
            ).all()

            pages_redirect = session.exec(
                select(CrawledPage).where(
                    CrawledPage.audit_run_id == audit_run.id,
                    CrawledPage.status_code >= 300,
                    CrawledPage.status_code < 400,
                )
            ).all()

            pages_error = session.exec(
                select(CrawledPage).where(
                    CrawledPage.audit_run_id == audit_run.id,
                    CrawledPage.status_code >= 400,
                )
            ).all()

            # Update stats
            if not audit_run.stats:
                audit_run.stats = {}
            audit_run.stats.update(
                {
                    "total_pages": pages_crawled,
                    "pages_ok": len(pages_ok),
                    "pages_redirect": len(pages_redirect),
                    "pages_error": len(pages_error),
                    "avg_response_time_ms": avg_response_time,
                }
            )
            session.add(audit_run)
            session.commit()

            return {"pages_crawled": pages_crawled}

        except Exception as e:
            # Update status to FAILED
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if audit_run:
                audit_run.status = AuditStatus.FAILED
                audit_run.error_message = str(e)[:2000]
                session.add(audit_run)
                session.commit()
            raise


@shared_task(name="app.tasks.audit.render_pages", bind=True)  # type: ignore[misc]
def render_pages(
    self: "Task", crawl_result: dict[str, Any], project_id: str, audit_run_id: str  # noqa: ARG001
) -> dict[str, Any]:
    """
    Render JavaScript-heavy pages with Playwright.

    Args:
        self: Task instance (bound)
        crawl_result: Result from crawl_pages task
        project_id: UUID of the project
        audit_run_id: UUID of the audit run

    Returns:
        Dict with pages_rendered count
    """
    with Session(engine) as session:
        try:
            # Get audit run
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if not audit_run:
                raise ValueError(f"AuditRun {audit_run_id} not found")

            # Check if JS rendering is enabled
            config = audit_run.config
            if not config.get("enable_js_rendering", False):
                return {"pages_rendered": 0}

            # Update status to RENDERING
            audit_run.status = AuditStatus.RENDERING
            session.add(audit_run)
            session.commit()

            # Get pages that need rendering based on js_render_mode
            js_render_mode = config.get("js_render_mode", "hybrid")
            max_render_pages = config.get("max_render_pages", 100)

            # Get pages to render
            if js_render_mode == "all":
                # Render all pages
                statement = (
                    select(CrawledPage)
                    .where(CrawledPage.audit_run_id == audit_run.id)
                    .limit(max_render_pages)
                )
            else:
                # Hybrid mode: only render pages with low word count or missing critical elements
                # Use bitwise operators for SQLAlchemy expressions
                from sqlalchemy import or_, and_
                statement = (
                    select(CrawledPage)
                    .where(CrawledPage.audit_run_id == audit_run.id)
                    .where(
                        or_(
                            and_(CrawledPage.word_count != None, CrawledPage.word_count < 50),  # type: ignore[arg-type, operator]  # noqa: E711
                            CrawledPage.title == None,  # type: ignore[arg-type]  # noqa: E711
                            CrawledPage.title == "",  # type: ignore[arg-type]
                            CrawledPage.h1_count == 0,  # type: ignore[arg-type]
                        )
                    )
                    .limit(max_render_pages)
                )

            pages_to_render = session.exec(statement).all()

            # Initialize renderer
            renderer = Renderer(
                timeout_ms=config.get("render_timeout_ms", 30000),
                user_agent=config.get("user_agent", "SEOPlatformBot/1.0"),
            )

            pages_rendered = 0

            async def run_rendering() -> None:
                nonlocal pages_rendered
                await renderer.start()

                try:
                    for page in pages_to_render:
                        # Render the page
                        render_result = await renderer.render(page.final_url)

                        # Update page with rendered data
                        if not render_result.error:
                            page.is_rendered = True
                            page.rendered_at = datetime.now(timezone.utc)
                            page.rendered_title = render_result.title
                            page.rendered_meta_description = (
                                render_result.meta_description
                            )
                            page.rendered_h1_count = render_result.h1_count
                            page.rendered_word_count = render_result.word_count
                            session.add(page)
                            pages_rendered += 1

                        # Update progress
                        if pages_rendered % 5 == 0:
                            assert audit_run is not None
                            session.commit()
                            # Calculate progress
                            audit_run.progress_pct = 20 + min(20.0, (pages_rendered / len(pages_to_render)) * 20)
                            audit_run.progress_message = (
                                f"Rendered {pages_rendered} pages"
                            )
                            session.add(audit_run)
                            session.commit()

                finally:
                    await renderer.stop()

            # Run rendering
            asyncio.run(run_rendering())

            # Final commit
            session.commit()

            return {"pages_rendered": pages_rendered}

        except Exception as e:
            # Update status to FAILED
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if audit_run:
                audit_run.status = AuditStatus.FAILED
                audit_run.error_message = str(e)[:2000]
                session.add(audit_run)
                session.commit()
            raise


@shared_task(name="app.tasks.audit.analyze_pages", bind=True)  # type: ignore[misc]
def analyze_pages(
    self: "Task", render_result: dict[str, Any], project_id: str, audit_run_id: str  # noqa: ARG001
) -> dict[str, Any]:
    """
    Analyze crawled pages and detect SEO issues.

    Args:
        self: Task instance (bound)
        render_result: Result from render_pages task
        project_id: UUID of the project
        audit_run_id: UUID of the audit run

    Returns:
        Dict with issue counts by severity and type
    """
    with Session(engine) as session:
        try:
            # Get audit run and project
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if not audit_run:
                raise ValueError(f"AuditRun {audit_run_id} not found")

            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Update status to ANALYZING
            audit_run.status = AuditStatus.ANALYZING
            session.add(audit_run)
            session.commit()

            # Initialize analyzer and duplicate detector
            analyzer = IssueAnalyzer(seed_url=project.seed_url)
            duplicate_detector = DuplicateDetector()

            # Get all pages
            statement = select(CrawledPage).where(
                CrawledPage.audit_run_id == audit_run.id
            )
            pages = session.exec(statement).all()

            # First pass: add pages to duplicate detector
            for page in pages:
                title = page.rendered_title if page.is_rendered else page.title
                duplicate_detector.add_page(
                    url=page.url, title=title, content_hash=page.content_hash
                )

            # Second pass: analyze each page
            issues_by_severity: dict[str, int] = {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            }
            issues_by_type: dict[str, int] = {}

            for i, page in enumerate(pages):
                # Analyze page
                for detected_issue in analyzer.analyze_page(page):
                    # Create AuditIssue record
                    issue = AuditIssue(
                        audit_run_id=audit_run.id,
                        page_url=detected_issue.page_url,
                        issue_type=detected_issue.issue_type,
                        severity=detected_issue.severity,
                        details=detected_issue.details,
                        is_new=True,  # Will be updated in compute_diff
                    )
                    session.add(issue)

                    # Update counts
                    issues_by_severity[detected_issue.severity.value] = (
                        issues_by_severity.get(detected_issue.severity.value, 0) + 1
                    )
                    issues_by_type[detected_issue.issue_type.value] = (
                        issues_by_type.get(detected_issue.issue_type.value, 0) + 1
                    )

                # Update progress
                if (i + 1) % 10 == 0:
                    session.commit()
                    audit_run.progress_pct = 40 + min(
                        30.0, ((i + 1) / len(pages)) * 30
                    )
                    audit_run.progress_message = f"Analyzed {i + 1}/{len(pages)} pages"
                    session.add(audit_run)
                    session.commit()

            # Add duplicate title issues
            for detected_issue in duplicate_detector.get_duplicate_title_issues():
                issue = AuditIssue(
                    audit_run_id=audit_run.id,
                    page_url=detected_issue.page_url,
                    issue_type=detected_issue.issue_type,
                    severity=detected_issue.severity,
                    details=detected_issue.details,
                    is_new=True,
                )
                session.add(issue)

                # Update counts
                issues_by_severity[detected_issue.severity.value] = (
                    issues_by_severity.get(detected_issue.severity.value, 0) + 1
                )
                issues_by_type[detected_issue.issue_type.value] = (
                    issues_by_type.get(detected_issue.issue_type.value, 0) + 1
                )

            # Final commit
            session.commit()

            # Update stats
            if not audit_run.stats:
                audit_run.stats = {}
            audit_run.stats.update(
                {
                    "total_issues": sum(issues_by_severity.values()),
                    "issues_critical": issues_by_severity.get("critical", 0),
                    "issues_high": issues_by_severity.get("high", 0),
                    "issues_medium": issues_by_severity.get("medium", 0),
                    "issues_low": issues_by_severity.get("low", 0),
                }
            )
            session.add(audit_run)
            session.commit()

            return {
                "issues_by_severity": issues_by_severity,
                "issues_by_type": issues_by_type,
            }

        except Exception as e:
            # Update status to FAILED
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if audit_run:
                audit_run.status = AuditStatus.FAILED
                audit_run.error_message = str(e)[:2000]
                session.add(audit_run)
                session.commit()
            raise


@shared_task(name="app.tasks.audit.compute_diff", bind=True)  # type: ignore[misc]
def compute_diff(
    self: "Task", analyze_result: dict[str, Any], project_id: str, audit_run_id: str  # noqa: ARG001
) -> dict[str, Any]:
    """
    Compare current audit with previous run to track new/resolved issues.

    Args:
        self: Task instance (bound)
        analyze_result: Result from analyze_pages task
        project_id: UUID of the project
        audit_run_id: UUID of the audit run

    Returns:
        Dict with diff counts (new, resolved, unchanged issues)
    """
    with Session(engine) as session:
        try:
            # Get audit run and project
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if not audit_run:
                raise ValueError(f"AuditRun {audit_run_id} not found")

            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Update status to DIFFING
            audit_run.status = AuditStatus.DIFFING
            audit_run.progress_pct = 70.0
            audit_run.progress_message = "Computing diff with previous run"
            session.add(audit_run)
            session.commit()

            # Initialize differ
            differ = AuditDiffer(session)

            # Get previous run
            previous_run = differ.get_previous_run(
                project_id=uuid.UUID(project_id), current_run_id=uuid.UUID(audit_run_id)
            )

            # Compute diff
            diff_result = differ.compute_diff(audit_run, previous_run)

            # Update status to COMPLETED
            audit_run.status = AuditStatus.COMPLETED
            audit_run.finished_at = datetime.now(timezone.utc)
            audit_run.progress_pct = 100.0
            audit_run.progress_message = "Audit completed"
            session.add(audit_run)

            # Update project last_audit_at
            project.last_audit_at = datetime.now(timezone.utc)
            session.add(project)

            session.commit()

            return {
                "new_issues": diff_result.new_issues,
                "resolved_issues": diff_result.resolved_issues,
                "unchanged_issues": diff_result.unchanged_issues,
            }

        except Exception as e:
            # Update status to FAILED
            audit_run = session.get(AuditRun, uuid.UUID(audit_run_id))
            if audit_run:
                audit_run.status = AuditStatus.FAILED
                audit_run.error_message = str(e)[:2000]
                session.add(audit_run)
                session.commit()
            raise
