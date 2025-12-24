"""
Celery tasks for GSC (Google Search Console) workflow.

This module implements the GSC pipeline:
1. sync_gsc_property: Daily sync of GSC data
2. backfill_gsc_data: Historical data backfill
3. compute_opportunities: Find keyword opportunities
4. cluster_queries: Generate query clusters
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from sqlmodel import Session, select

from app.core.cache import invalidate_gsc_cache
from app.core.db import engine
from app.core.oauth.google import GoogleOAuthClient
from app.models.gsc import GSCProperty
from app.models.integration import IntegrationAccount
from app.models.project import Project
from app.services.gsc.client import GSCClient
from app.services.gsc.clustering import QueryClusterer
from app.services.gsc.ingestor import GSCIngestor
from app.services.gsc.opportunities import OpportunityFinder


@shared_task(bind=True, name="app.tasks.gsc.sync_gsc_property")  # type: ignore[misc]
def sync_gsc_property(self, project_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """
    Daily sync task for a linked GSC property.

    Steps:
    1. Get project and gsc_property from DB
    2. Get integration account for user
    3. Decrypt and refresh tokens if expired
    4. Create GSCClient and GSCIngestor
    5. Sync last 3 days of data
    6. Update property status and project timestamp
    7. Return {queries: count, pages: count}

    Args:
        project_id: UUID of the project

    Returns:
        Dictionary with sync results or error
    """
    try:
        with Session(engine) as session:
            # Step 1: Get project and gsc_property from DB
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {"error": "Project not found"}

            gsc_property = project.gsc_property
            if not gsc_property:
                return {"error": "GSC property not found"}

            # Step 2: Get integration account for user
            stmt = select(IntegrationAccount).where(
                IntegrationAccount.user_id == project.created_by_id,
                IntegrationAccount.provider == "google_gsc"
            )
            account = session.exec(stmt).first()
            if not account:
                return {"error": "Integration account not found"}

            # Step 3: Decrypt and refresh tokens if expired
            oauth_client = GoogleOAuthClient()
            access_token = oauth_client.decrypt_token(account.access_token_encrypted)
            refresh_token = oauth_client.decrypt_token(account.refresh_token_encrypted)

            # Check if token is expired
            if account.token_expires_at < datetime.now(timezone.utc):
                # Refresh the token
                token_response = asyncio.run(oauth_client.refresh_token(refresh_token))
                access_token = token_response["access_token"]
                expires_in = token_response.get("expires_in", 3600)

                # Update account with new token
                account.access_token_encrypted = oauth_client.encrypt_token(access_token)
                account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                session.add(account)

            # Step 4: Create GSCClient and GSCIngestor
            gsc_client = GSCClient(
                access_token=access_token,
                refresh_token=refresh_token
            )
            ingestor = GSCIngestor(session=session, client=gsc_client)

            # Step 5: Sync last 3 days of data
            today = date.today()
            end_date = today - timedelta(days=3)  # GSC data has ~3 day delay
            start_date = end_date - timedelta(days=2)  # Last 3 days

            # Update property status to syncing
            gsc_property.sync_status = "syncing"
            gsc_property.sync_error = None
            session.add(gsc_property)
            session.commit()

            # Sync queries and pages
            queries_count = asyncio.run(ingestor.sync_queries(
                project_id=project.id,
                site_url=gsc_property.site_url,
                start_date=start_date,
                end_date=end_date,
                include_page=True
            ))

            pages_count = asyncio.run(ingestor.sync_pages(
                project_id=project.id,
                site_url=gsc_property.site_url,
                start_date=start_date,
                end_date=end_date
            ))

            # Step 6: Update property status and project timestamp
            gsc_property.last_sync_at = datetime.now(timezone.utc)
            gsc_property.sync_status = "completed"
            project.last_gsc_sync_at = datetime.now(timezone.utc)

            session.add(gsc_property)
            session.add(project)
            session.commit()

            # Step 7: Invalidate cache for this project
            invalidate_gsc_cache(project_id)

            # Step 8: Return results
            return {
                "queries": queries_count,
                "pages": pages_count
            }

    except Exception as e:
        # Update property status on error
        try:
            with Session(engine) as session:
                gsc_property = session.exec(
                    select(GSCProperty).where(GSCProperty.project_id == uuid.UUID(project_id))
                ).first()
                if gsc_property:
                    gsc_property.sync_status = "error"
                    gsc_property.sync_error = str(e)[:2000]
                    session.add(gsc_property)
                    session.commit()
        except Exception:
            pass

        return {"error": str(e)}


@shared_task(bind=True, name="app.tasks.gsc.backfill_gsc_data")  # type: ignore[misc]
def backfill_gsc_data(self, project_id: str, days: int = 90) -> dict[str, Any]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """
    Backfill historical GSC data.

    Similar flow to sync but calls ingestor.backfill()

    Args:
        project_id: UUID of the project
        days: Number of days to backfill (default: 90)

    Returns:
        Dictionary with backfill results or error
    """
    try:
        with Session(engine) as session:
            # Get project and gsc_property from DB
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {"error": "Project not found"}

            gsc_property = project.gsc_property
            if not gsc_property:
                return {"error": "GSC property not found"}

            # Get integration account for user
            stmt = select(IntegrationAccount).where(
                IntegrationAccount.user_id == project.created_by_id,
                IntegrationAccount.provider == "google_gsc"
            )
            account = session.exec(stmt).first()
            if not account:
                return {"error": "Integration account not found"}

            # Decrypt and refresh tokens if expired
            oauth_client = GoogleOAuthClient()
            access_token = oauth_client.decrypt_token(account.access_token_encrypted)
            refresh_token = oauth_client.decrypt_token(account.refresh_token_encrypted)

            # Check if token is expired
            if account.token_expires_at < datetime.now(timezone.utc):
                # Refresh the token
                token_response = asyncio.run(oauth_client.refresh_token(refresh_token))
                access_token = token_response["access_token"]
                expires_in = token_response.get("expires_in", 3600)

                # Update account with new token
                account.access_token_encrypted = oauth_client.encrypt_token(access_token)
                account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                session.add(account)

            # Create GSCClient and GSCIngestor
            gsc_client = GSCClient(
                access_token=access_token,
                refresh_token=refresh_token
            )
            ingestor = GSCIngestor(session=session, client=gsc_client)

            # Update property status to backfilling
            gsc_property.sync_status = "backfilling"
            gsc_property.sync_error = None
            session.add(gsc_property)
            session.commit()

            # Call backfill
            result = asyncio.run(ingestor.backfill(
                project_id=project.id,
                site_url=gsc_property.site_url,
                days=days
            ))

            # Update property status and project timestamp
            gsc_property.last_sync_at = datetime.now(timezone.utc)
            gsc_property.sync_status = "completed"
            project.last_gsc_sync_at = datetime.now(timezone.utc)

            session.add(gsc_property)
            session.add(project)
            session.commit()

            # Invalidate cache for this project
            invalidate_gsc_cache(project_id)

            return result

    except Exception as e:
        # Update property status on error
        try:
            with Session(engine) as session:
                gsc_property = session.exec(
                    select(GSCProperty).where(GSCProperty.project_id == uuid.UUID(project_id))
                ).first()
                if gsc_property:
                    gsc_property.sync_status = "error"
                    gsc_property.sync_error = str(e)[:2000]
                    session.add(gsc_property)
                    session.commit()
        except Exception:
            pass

        return {"error": str(e)}


@shared_task(bind=True, name="app.tasks.gsc.compute_opportunities")  # type: ignore[misc]
def compute_opportunities(self, project_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """
    Compute keyword opportunities.

    Steps:
    - Create OpportunityFinder
    - Call find_opportunities
    - Return {total: count, by_type: {type: count}}

    Args:
        project_id: UUID of the project

    Returns:
        Dictionary with opportunities or error
    """
    try:
        with Session(engine) as session:
            # Get project
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {"error": "Project not found"}

            # Create OpportunityFinder
            finder = OpportunityFinder(session=session)

            # Find opportunities (returns an iterator)
            opportunities = list(finder.find_opportunities(project_id=project.id))

            # Count by type
            by_type: dict[str, int] = {}
            for opp in opportunities:
                opp_type = opp.opportunity_type.value
                by_type[opp_type] = by_type.get(opp_type, 0) + 1

            return {
                "total": len(opportunities),
                "by_type": by_type
            }

    except Exception as e:
        return {"error": str(e)}


@shared_task(bind=True, name="app.tasks.gsc.cluster_queries")  # type: ignore[misc]
def cluster_queries(self, project_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """
    Generate query clusters.

    Steps:
    - Create QueryClusterer
    - Call cluster_queries
    - Return {clusters_created: count}

    Args:
        project_id: UUID of the project

    Returns:
        Dictionary with cluster count or error
    """
    try:
        with Session(engine) as session:
            # Get project
            project = session.get(Project, uuid.UUID(project_id))
            if not project:
                return {"error": "Project not found"}

            # Create QueryClusterer
            clusterer = QueryClusterer(session=session)

            # Generate clusters
            clusters_created = clusterer.cluster_queries(project_id=project.id)

            return {"clusters_created": clusters_created}

    except Exception as e:
        return {"error": str(e)}
