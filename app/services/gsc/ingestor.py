"""GSC Ingestor Service - Ingest GSC data into the database."""
import uuid
from datetime import date, timedelta

from sqlmodel import Session, delete

from app.models.gsc import GSCPageDaily, GSCQueryDaily
from app.services.gsc.client import GSCClient


class GSCIngestor:
    """Ingest GSC data into the database."""

    def __init__(self, session: Session, client: GSCClient) -> None:
        """
        Initialize the GSC ingestor.

        Args:
            session: Database session
            client: GSC API client
        """
        self.session = session
        self.client = client

    async def sync_queries(
        self,
        project_id: uuid.UUID,
        site_url: str,
        start_date: date,
        end_date: date,
        include_page: bool = True,
    ) -> int:
        """
        Sync query-level data for a date range.

        Returns number of rows inserted.

        Steps:
        1. Build dimensions list: ["query", "date"] + optionally ["page"]
        2. Delete existing data for date range (upsert approach)
        3. Iterate through client.query_all_rows()
        4. Parse keys[0]=query, keys[1]=date, keys[2]=page (if include_page)
        5. Create GSCQueryDaily records
        6. Commit in batches of 1000

        Args:
            project_id: Project UUID
            site_url: GSC property URL
            start_date: Start date for data sync
            end_date: End date for data sync
            include_page: Include page dimension in query

        Returns:
            Number of rows inserted
        """
        # Step 1: Build dimensions list
        dimensions = ["query", "date"]
        if include_page:
            dimensions.append("page")

        # Step 2: Delete existing data for date range (upsert)
        delete_stmt = delete(GSCQueryDaily).where(
            GSCQueryDaily.project_id == project_id,  # type: ignore
            GSCQueryDaily.date >= start_date,  # type: ignore
            GSCQueryDaily.date <= end_date,  # type: ignore
        )
        self.session.exec(delete_stmt)  # type: ignore
        self.session.commit()

        # Step 3-5: Iterate through client data and create records
        records_to_insert = []
        total_count = 0
        batch_size = 1000

        async for row in self.client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            # Parse keys
            keys = row["keys"]
            query = keys[0]
            row_date = date.fromisoformat(keys[1])
            page = keys[2] if include_page and len(keys) > 2 else None

            # Create record
            record = GSCQueryDaily(
                project_id=project_id,
                date=row_date,
                query=query,
                page=page,
                clicks=row["clicks"],
                impressions=row["impressions"],
                ctr=row["ctr"],
                position=row["position"],
            )
            records_to_insert.append(record)
            total_count += 1

            # Step 6: Commit in batches of 1000
            if len(records_to_insert) >= batch_size:
                self.session.add_all(records_to_insert)
                self.session.commit()
                records_to_insert = []

        # Commit remaining records
        if records_to_insert:
            self.session.add_all(records_to_insert)
            self.session.commit()

        return total_count

    async def sync_pages(
        self,
        project_id: uuid.UUID,
        site_url: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """
        Sync page-level aggregated data.

        Similar to sync_queries but uses GSCPageDaily.
        Dimensions: ["page", "date"]

        Args:
            project_id: Project UUID
            site_url: GSC property URL
            start_date: Start date for data sync
            end_date: End date for data sync

        Returns:
            Number of rows inserted
        """
        # Dimensions for page-level data
        dimensions = ["page", "date"]

        # Delete existing data for date range (upsert)
        delete_stmt = delete(GSCPageDaily).where(
            GSCPageDaily.project_id == project_id,  # type: ignore
            GSCPageDaily.date >= start_date,  # type: ignore
            GSCPageDaily.date <= end_date,  # type: ignore
        )
        self.session.exec(delete_stmt)  # type: ignore
        self.session.commit()

        # Iterate through client data and create records
        records_to_insert = []
        total_count = 0
        batch_size = 1000

        async for row in self.client.query_all_rows(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
        ):
            # Parse keys
            keys = row["keys"]
            page = keys[0]
            row_date = date.fromisoformat(keys[1])

            # Create record
            record = GSCPageDaily(
                project_id=project_id,
                date=row_date,
                page=page,
                clicks=row["clicks"],
                impressions=row["impressions"],
                ctr=row["ctr"],
                position=row["position"],
            )
            records_to_insert.append(record)
            total_count += 1

            # Commit in batches of 1000
            if len(records_to_insert) >= batch_size:
                self.session.add_all(records_to_insert)
                self.session.commit()
                records_to_insert = []

        # Commit remaining records
        if records_to_insert:
            self.session.add_all(records_to_insert)
            self.session.commit()

        return total_count

    async def backfill(
        self,
        project_id: uuid.UUID,
        site_url: str,
        days: int = 90,
        chunk_days: int = 7,
    ) -> dict[str, int]:
        """
        Backfill historical data in chunks.

        Steps:
        1. Calculate date range (today - 3 days - days) to (today - 3 days)
        2. Process in chunk_days increments
        3. Call sync_queries and sync_pages for each chunk
        4. Return {"queries": total, "pages": total}

        Args:
            project_id: Project UUID
            site_url: GSC property URL
            days: Number of days to backfill (default: 90)
            chunk_days: Size of each chunk in days (default: 7)

        Returns:
            Dictionary with total counts: {"queries": int, "pages": int}
        """
        # Step 1: Calculate date range (GSC data has ~3 day delay)
        today = date.today()
        end_date = today - timedelta(days=3)
        start_date = end_date - timedelta(days=days)

        total_queries = 0
        total_pages = 0

        # Step 2: Process in chunks
        current_start = start_date
        while current_start <= end_date:
            # Calculate chunk end date
            current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)

            # Step 3: Sync queries and pages for this chunk
            queries_count = await self.sync_queries(
                project_id=project_id,
                site_url=site_url,
                start_date=current_start,
                end_date=current_end,
                include_page=True,
            )
            total_queries += queries_count

            pages_count = await self.sync_pages(
                project_id=project_id,
                site_url=site_url,
                start_date=current_start,
                end_date=current_end,
            )
            total_pages += pages_count

            # Move to next chunk
            current_start = current_end + timedelta(days=1)

        # Step 4: Return totals
        return {"queries": total_queries, "pages": total_pages}
