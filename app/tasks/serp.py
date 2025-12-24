"""
Celery tasks for SERP/Rank Tracking workflow.

This module implements the SERP refresh pipeline:
1. refresh_keyword: Refresh a single keyword target
2. refresh_project_keywords: Refresh all due keywords for a project
3. refresh_all_due_keywords: Refresh all due keywords across all projects
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models.project import Project
from app.models.serp import KeywordTarget, RefreshStatus
from app.services.serp.tracker import RankTracker


@shared_task(name="app.tasks.serp.refresh_keyword")  # type: ignore[misc]
def refresh_keyword(keyword_target_id: str) -> dict[str, Any]:
    """
    Refresh ranking data for a single keyword target.

    This task:
    1. Gets KeywordTarget and Project from database
    2. Creates RankTracker instance
    3. Runs tracker.refresh_keyword() using asyncio.run()
    4. Returns dict with keyword, rank, status

    Args:
        keyword_target_id: UUID of the keyword target to refresh

    Returns:
        Dict with keyword, rank, status, and optional error
    """
    with Session(engine) as session:
        try:
            # Get KeywordTarget from database
            keyword_target = session.get(KeywordTarget, uuid.UUID(keyword_target_id))
            if not keyword_target:
                return {
                    "keyword": None,
                    "rank": None,
                    "status": RefreshStatus.FAILED,
                    "error": f"KeywordTarget {keyword_target_id} not found",
                }

            # Get Project from database
            project = session.get(Project, keyword_target.project_id)
            if not project:
                return {
                    "keyword": keyword_target.keyword,
                    "rank": None,
                    "status": RefreshStatus.FAILED,
                    "error": f"Project {keyword_target.project_id} not found",
                }

            # Create RankTracker instance
            tracker = RankTracker(session=session)

            # Run tracker.refresh_keyword() using asyncio.run()
            observation = asyncio.run(
                tracker.refresh_keyword(
                    keyword_target=keyword_target,
                    project=project
                )
            )

            # Return dict with keyword, rank, status
            return {
                "keyword": keyword_target.keyword,
                "rank": observation.rank,
                "status": observation.status,
                "url": observation.url,
            }

        except Exception as e:
            # Handle errors gracefully
            keyword = keyword_target.keyword if 'keyword_target' in locals() else None
            return {
                "keyword": keyword,
                "rank": None,
                "status": RefreshStatus.FAILED,
                "error": str(e),
            }


@shared_task(name="app.tasks.serp.refresh_project_keywords")  # type: ignore[misc]
def refresh_project_keywords(project_id: str) -> dict[str, Any]:
    """
    Refresh all due keywords for a project.

    This task:
    1. Gets Project from database
    2. Queries due KeywordTarget records (is_active=True, next refresh due)
    3. Respects SERP_REFRESH_DAILY_CAP from settings
    4. Refreshes each keyword using RankTracker
    5. Updates project.last_serp_refresh_at

    Args:
        project_id: UUID of the project

    Returns:
        Dict with refreshed count and results
    """
    with Session(engine) as session:
        try:
            # Get Project from database
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {
                    "refreshed_count": 0,
                    "results": [],
                    "error": f"Project {project_id} not found",
                }

            # Query due KeywordTarget records
            # A keyword is due if:
            # - is_active=True
            # - last_refresh_at is None OR (now - last_refresh_at) >= refresh_frequency_hours
            now = datetime.now(timezone.utc)

            # Build query for due keywords
            statement = (
                select(KeywordTarget)
                .where(KeywordTarget.project_id == uuid.UUID(project_id))
                .where(KeywordTarget.is_active == True)  # noqa: E712
            )

            all_active_keywords = session.exec(statement).all()

            # Filter to only due keywords
            due_keywords = []
            for keyword in all_active_keywords:
                if keyword.last_refresh_at is None:
                    # Never refreshed - it's due
                    due_keywords.append(keyword)
                else:
                    # Check if enough time has passed
                    time_since_refresh = now - keyword.last_refresh_at
                    if time_since_refresh >= timedelta(hours=keyword.refresh_frequency_hours):
                        due_keywords.append(keyword)

            # Respect SERP_REFRESH_DAILY_CAP
            keywords_to_refresh = due_keywords[:settings.SERP_REFRESH_DAILY_CAP]

            # Create RankTracker instance
            tracker = RankTracker(session=session)

            # Refresh each keyword
            results = []
            for keyword_target in keywords_to_refresh:
                try:
                    observation = asyncio.run(
                        tracker.refresh_keyword(
                            keyword_target=keyword_target,
                            project=project
                        )
                    )
                    results.append({
                        "keyword": keyword_target.keyword,
                        "rank": observation.rank,
                        "status": observation.status,
                    })
                except Exception as e:
                    results.append({
                        "keyword": keyword_target.keyword,
                        "rank": None,
                        "status": RefreshStatus.FAILED,
                        "error": str(e),
                    })

            # Update project.last_serp_refresh_at
            project.last_serp_refresh_at = datetime.now(timezone.utc)
            session.add(project)
            session.commit()

            return {
                "refreshed_count": len(results),
                "results": results,
            }

        except Exception as e:
            return {
                "refreshed_count": 0,
                "results": [],
                "error": str(e),
            }


@shared_task(name="app.tasks.serp.refresh_all_due_keywords")  # type: ignore[misc]
def refresh_all_due_keywords() -> dict[str, Any]:
    """
    Refresh all due keywords across all projects.

    This task:
    1. Queries all due keywords across all projects
    2. Groups by project_id
    3. Queues refresh_project_keywords.delay() for each project

    Returns:
        Dict with projects_queued and total_keywords
    """
    with Session(engine) as session:
        try:
            # Query all due keywords across all projects
            now = datetime.now(timezone.utc)

            # Get all active keywords
            statement = select(KeywordTarget).where(KeywordTarget.is_active == True)  # noqa: E712
            all_keywords = session.exec(statement).all()

            # Filter to only due keywords and group by project_id
            projects_with_due_keywords: dict[uuid.UUID, int] = {}

            for keyword in all_keywords:
                is_due = False

                if keyword.last_refresh_at is None:
                    # Never refreshed - it's due
                    is_due = True
                else:
                    # Check if enough time has passed
                    time_since_refresh = now - keyword.last_refresh_at
                    if time_since_refresh >= timedelta(hours=keyword.refresh_frequency_hours):
                        is_due = True

                if is_due:
                    if keyword.project_id not in projects_with_due_keywords:
                        projects_with_due_keywords[keyword.project_id] = 0
                    projects_with_due_keywords[keyword.project_id] += 1

            # Queue refresh_project_keywords.delay() for each project
            total_keywords = sum(projects_with_due_keywords.values())

            for project_id in projects_with_due_keywords.keys():
                refresh_project_keywords.delay(str(project_id))

            return {
                "projects_queued": len(projects_with_due_keywords),
                "total_keywords": total_keywords,
            }

        except Exception as e:
            return {
                "projects_queued": 0,
                "total_keywords": 0,
                "error": str(e),
            }
