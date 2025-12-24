"""
Maintenance tasks for data cleanup and health monitoring.

Sprint 6: Hardening - Retention policies and maintenance tasks
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.celery import celery_app
from app.core.config import settings
from app.core.db import engine
from app.models.ads import AdsCampaignDaily, AdsKeywordDaily
from app.models.audit import AuditIssue, AuditRun, CrawledPage
from app.models.gsc import GSCPageDaily, GSCQueryDaily
from app.models.job import JobRun
from app.models.links import BacklinkEdge, LinkSnapshot
from app.models.serp import RankObservation, SerpSnapshot

logger = logging.getLogger(__name__)


@shared_task
def cleanup_old_data() -> dict:
    """
    Clean up old data based on retention policies.

    Deletes:
    1. Old JobRun records (7 days default)
    2. Old SerpSnapshot records (90 days default)
    3. Old AuditRun records (30 days, keep last 10 per project)
    4. Old LinkSnapshot records (60 days)
    5. Old GSC daily data (365 days)
    6. Old Ads daily data (365 days)

    Returns:
        dict: Counts of deleted records by type
    """
    logger.info("Starting cleanup_old_data task")

    counts = {
        "job_runs_deleted": 0,
        "serp_snapshots_deleted": 0,
        "audit_runs_deleted": 0,
        "link_snapshots_deleted": 0,
        "gsc_query_deleted": 0,
        "gsc_page_deleted": 0,
        "ads_campaign_deleted": 0,
        "ads_keyword_deleted": 0,
    }

    with Session(engine) as session:
        # 1. Clean up old JobRun records
        try:
            job_runs_cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.RETENTION_JOB_RUNS
            )
            job_runs_stmt = select(JobRun).where(JobRun.queued_at < job_runs_cutoff)
            old_job_runs = session.exec(job_runs_stmt).all()

            for run in old_job_runs:
                session.delete(run)

            counts["job_runs_deleted"] = len(old_job_runs)
            session.commit()
            logger.info(f"Deleted {counts['job_runs_deleted']} old JobRun records")
        except Exception as e:
            logger.error(f"Error cleaning up JobRun records: {e}")
            session.rollback()

        # 2. Clean up old SerpSnapshot records
        try:
            serp_cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.RETENTION_SERP_SNAPSHOTS
            )
            serp_stmt = select(SerpSnapshot).where(
                SerpSnapshot.captured_at < serp_cutoff
            )
            old_snapshots = session.exec(serp_stmt).all()

            for snapshot in old_snapshots:
                session.delete(snapshot)

            counts["serp_snapshots_deleted"] = len(old_snapshots)
            session.commit()
            logger.info(
                f"Deleted {counts['serp_snapshots_deleted']} old SerpSnapshot records"
            )
        except Exception as e:
            logger.error(f"Error cleaning up SerpSnapshot records: {e}")
            session.rollback()

        # 3. Clean up old AuditRun records (keep last 10 per project)
        try:
            # Use the dedicated cleanup function for audit runs
            audit_result = _cleanup_audit_runs_internal(session, project_id=None)
            counts["audit_runs_deleted"] = audit_result["audit_runs_deleted"]
            logger.info(
                f"Deleted {counts['audit_runs_deleted']} old AuditRun records"
            )
        except Exception as e:
            logger.error(f"Error cleaning up AuditRun records: {e}")
            session.rollback()

        # 4. Clean up old LinkSnapshot records
        try:
            links_cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.RETENTION_LINK_SNAPSHOTS
            )
            links_stmt = select(LinkSnapshot).where(
                LinkSnapshot.ingested_at < links_cutoff
            )
            old_link_snapshots = session.exec(links_stmt).all()

            for snapshot in old_link_snapshots:
                session.delete(snapshot)

            counts["link_snapshots_deleted"] = len(old_link_snapshots)
            session.commit()
            logger.info(
                f"Deleted {counts['link_snapshots_deleted']} old LinkSnapshot records"
            )
        except Exception as e:
            logger.error(f"Error cleaning up LinkSnapshot records: {e}")
            session.rollback()

        # 5. Clean up old GSC daily data
        try:
            gsc_cutoff = (
                datetime.now(timezone.utc) - timedelta(days=settings.RETENTION_GSC_DAILY)
            ).date()

            # Delete old GSCQueryDaily records
            gsc_query_stmt = select(GSCQueryDaily).where(GSCQueryDaily.date < gsc_cutoff)
            old_gsc_queries = session.exec(gsc_query_stmt).all()

            for record in old_gsc_queries:
                session.delete(record)

            counts["gsc_query_deleted"] = len(old_gsc_queries)

            # Delete old GSCPageDaily records
            gsc_page_stmt = select(GSCPageDaily).where(GSCPageDaily.date < gsc_cutoff)
            old_gsc_pages = session.exec(gsc_page_stmt).all()

            for record in old_gsc_pages:
                session.delete(record)

            counts["gsc_page_deleted"] = len(old_gsc_pages)

            session.commit()
            logger.info(
                f"Deleted {counts['gsc_query_deleted']} GSCQueryDaily and "
                f"{counts['gsc_page_deleted']} GSCPageDaily records"
            )
        except Exception as e:
            logger.error(f"Error cleaning up GSC daily data: {e}")
            session.rollback()

        # 6. Clean up old Ads daily data
        try:
            ads_cutoff = (
                datetime.now(timezone.utc) - timedelta(days=settings.RETENTION_ADS_DAILY)
            ).date()

            # Delete old AdsCampaignDaily records
            ads_campaign_stmt = select(AdsCampaignDaily).where(
                AdsCampaignDaily.date < ads_cutoff
            )
            old_ads_campaigns = session.exec(ads_campaign_stmt).all()

            for record in old_ads_campaigns:
                session.delete(record)

            counts["ads_campaign_deleted"] = len(old_ads_campaigns)

            # Delete old AdsKeywordDaily records
            ads_keyword_stmt = select(AdsKeywordDaily).where(
                AdsKeywordDaily.date < ads_cutoff
            )
            old_ads_keywords = session.exec(ads_keyword_stmt).all()

            for record in old_ads_keywords:
                session.delete(record)

            counts["ads_keyword_deleted"] = len(old_ads_keywords)

            session.commit()
            logger.info(
                f"Deleted {counts['ads_campaign_deleted']} AdsCampaignDaily and "
                f"{counts['ads_keyword_deleted']} AdsKeywordDaily records"
            )
        except Exception as e:
            logger.error(f"Error cleaning up Ads daily data: {e}")
            session.rollback()

    logger.info(f"Cleanup completed: {counts}")
    return counts


def _cleanup_audit_runs_internal(
    session: Session, project_id: uuid.UUID | None = None
) -> dict:
    """
    Internal function to clean old audit runs.

    Keeps the last 10 audit runs per project and deletes older ones.

    Args:
        session: Database session
        project_id: Optional project ID to clean (None = all projects)

    Returns:
        dict: Count of deleted audit runs
    """
    deleted_count = 0

    # Get all projects or just the specified one
    if project_id:
        from app.models.project import Project

        project_stmt = select(Project).where(Project.id == project_id)
        projects = session.exec(project_stmt).all()
    else:
        from app.models.project import Project

        project_stmt = select(Project)
        projects = session.exec(project_stmt).all()

    # For each project, keep last 10 audit runs
    for project in projects:
        # Get all audit runs for this project, ordered by created_at DESC
        audit_stmt = (
            select(AuditRun)
            .where(AuditRun.project_id == project.id)
            .order_by(AuditRun.created_at.desc())
        )
        audit_runs = session.exec(audit_stmt).all()

        # If more than 10, delete the oldest ones
        if len(audit_runs) > 10:
            runs_to_delete = audit_runs[10:]  # Keep first 10, delete rest

            for run in runs_to_delete:
                session.delete(run)
                deleted_count += 1

    session.commit()
    return {"audit_runs_deleted": deleted_count}


@shared_task
def cleanup_audit_runs(project_id: str | None = None) -> dict:
    """
    Clean old audit runs for a specific project or all projects.

    Keeps the last 10 audit runs per project.
    Deletes associated CrawledPage and Issue records (CASCADE).

    Args:
        project_id: Optional project ID (string UUID). If None, cleans all projects.

    Returns:
        dict: Count of deleted audit runs
    """
    logger.info(f"Starting cleanup_audit_runs for project_id={project_id}")

    with Session(engine) as session:
        # Convert string UUID to UUID if provided
        project_uuid = uuid.UUID(project_id) if project_id else None

        result = _cleanup_audit_runs_internal(session, project_uuid)

        logger.info(
            f"Deleted {result['audit_runs_deleted']} audit runs for "
            f"project_id={project_id or 'all'}"
        )
        return result


@shared_task
def vacuum_database() -> dict:
    """
    Run VACUUM ANALYZE on frequently updated tables.

    Should be run during low-traffic periods (scheduled for weekly).
    Reclaims space and updates statistics for query planner.

    Returns:
        dict: Status and tables vacuumed
    """
    logger.info("Starting vacuum_database task")

    tables = [
        "job_runs",
        "serp_snapshots",
        "rank_observations",
        "audit_runs",
        "crawled_pages",
        "audit_issues",
        "gsc_query_daily",
        "gsc_page_daily",
        "ads_campaign_daily",
        "ads_keyword_daily",
        "link_snapshots",
        "backlink_edges",
    ]

    vacuumed_tables = []
    errors = []

    with engine.connect() as conn:
        # Use autocommit mode for VACUUM
        conn.execution_options(isolation_level="AUTOCOMMIT")

        for table in tables:
            try:
                logger.info(f"Running VACUUM ANALYZE on {table}")
                conn.execute(text(f"VACUUM ANALYZE {table}"))
                vacuumed_tables.append(table)
            except Exception as e:
                logger.error(f"Error vacuuming table {table}: {e}")
                errors.append({"table": table, "error": str(e)})

    result = {
        "status": "completed" if not errors else "completed_with_errors",
        "tables_vacuumed": vacuumed_tables,
        "errors": errors,
    }

    logger.info(f"Vacuum completed: {len(vacuumed_tables)} tables vacuumed")
    return result


@shared_task
def health_check() -> dict:
    """
    Basic health check task - tests DB and Redis connectivity.

    Returns:
        dict: Health status with DB and Redis connection status
    """
    logger.info("Running health check")

    status = {
        "status": "healthy",
        "db_connected": False,
        "redis_connected": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Test database connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["db_connected"] = True
        logger.info("Database connection: OK")
    except Exception as e:
        status["status"] = "unhealthy"
        status["db_connected"] = False
        status["error"] = f"Database error: {str(e)}"
        logger.error(f"Database connection failed: {e}")

    # Test Redis connection (via Celery broker)
    try:
        with celery_app.broker_connection() as conn:
            conn.connect()
        status["redis_connected"] = True
        logger.info("Redis connection: OK")
    except Exception as e:
        status["status"] = "unhealthy"
        status["redis_connected"] = False
        status["error"] = status.get("error", "") + f" Redis error: {str(e)}"
        logger.error(f"Redis connection failed: {e}")

    logger.info(f"Health check completed: {status['status']}")
    return status
