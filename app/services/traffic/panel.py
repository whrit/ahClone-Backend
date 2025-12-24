"""Traffic Panel Service - Aggregate traffic data from multiple sources."""
import uuid
from datetime import date, timedelta

from sqlmodel import Session, func, select

from app.models.ads import TrafficDaily
from app.models.gsc import GSCQueryDaily


class TrafficPanelService:
    """Aggregate traffic from multiple sources."""

    def __init__(self, session: Session):
        """
        Initialize the traffic panel service.

        Args:
            session: Database session
        """
        self.session = session

    def get_panel_data(
        self,
        project_id: str | uuid.UUID,
        period_days: int = 28
    ) -> list[dict]:
        """
        Get combined traffic panel data.

        Steps:
        1. Generate list of dates in range
        2. Query GA4 data from TrafficDaily where source_key='ga4'
        3. Query GSC clicks from GSCQueryDaily (aggregated by date)
        4. Query CrUX data from TrafficDaily where source_key='crux'
        5. Combine all sources by date
        6. Return list of dicts with: date, ga4_sessions, ga4_users, gsc_clicks, lcp, cls

        Args:
            project_id: Project UUID or string UUID
            period_days: Number of days to retrieve (default 28)

        Returns:
            List of dicts with combined traffic data for each date
        """
        # Convert string to UUID if needed
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)

        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=period_days - 1)

        # Get data from all sources
        ga4_data = self._get_ga4_data(project_id, start_date, end_date)
        gsc_clicks = self._get_gsc_clicks(project_id, start_date, end_date)
        crux_data = self._get_crux_data(project_id, start_date, end_date)

        # Generate date range and combine data
        result = []
        current_date = start_date

        while current_date <= end_date:
            row = {
                "date": current_date,
                "ga4_sessions": None,
                "ga4_users": None,
                "ga4_pageviews": None,
                "gsc_clicks": None,
                "lcp": None,
                "cls": None,
            }

            # Add GA4 data if available
            if current_date in ga4_data:
                ga4_info = ga4_data[current_date]
                row["ga4_sessions"] = ga4_info.get("sessions")
                row["ga4_users"] = ga4_info.get("users")
                row["ga4_pageviews"] = ga4_info.get("pageviews")

            # Add GSC clicks if available
            if current_date in gsc_clicks:
                row["gsc_clicks"] = gsc_clicks[current_date]

            # Add CrUX data if available
            if current_date in crux_data:
                crux_info = crux_data[current_date]
                row["lcp"] = crux_info.get("lcp")
                row["cls"] = crux_info.get("cls")

            result.append(row)
            current_date += timedelta(days=1)

        return result

    def _get_ga4_data(
        self,
        project_id: uuid.UUID,
        start_date: date,
        end_date: date
    ) -> dict[date, dict]:
        """
        Get GA4 data by date from TrafficDaily.

        Args:
            project_id: Project UUID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict mapping date to GA4 metrics (sessions, users, pageviews)
        """
        statement = select(TrafficDaily).where(
            TrafficDaily.project_id == project_id,
            TrafficDaily.source_key == "ga4",
            TrafficDaily.date >= start_date,
            TrafficDaily.date <= end_date
        )

        results = self.session.exec(statement).all()

        # Build dict of date -> metrics
        ga4_dict = {}
        for row in results:
            ga4_dict[row.date] = {
                "sessions": row.sessions,
                "users": row.users,
                "pageviews": row.pageviews,
            }

        return ga4_dict

    def _get_gsc_clicks(
        self,
        project_id: uuid.UUID,
        start_date: date,
        end_date: date
    ) -> dict[date, int]:
        """
        Get GSC clicks by date from GSCQueryDaily (sum of clicks per date).

        Args:
            project_id: Project UUID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict mapping date to total clicks
        """
        statement = (
            select(
                GSCQueryDaily.date,
                func.sum(GSCQueryDaily.clicks).label("total_clicks")
            )
            .where(
                GSCQueryDaily.project_id == project_id,
                GSCQueryDaily.date >= start_date,
                GSCQueryDaily.date <= end_date
            )
            .group_by(GSCQueryDaily.date)
        )

        results = self.session.exec(statement).all()

        # Build dict of date -> total clicks
        clicks_dict = {}
        for row in results:
            clicks_dict[row.date] = row.total_clicks

        return clicks_dict

    def _get_crux_data(
        self,
        project_id: uuid.UUID,
        start_date: date,
        end_date: date
    ) -> dict[date, dict]:
        """
        Get CrUX Core Web Vitals data by date from TrafficDaily.

        Args:
            project_id: Project UUID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict mapping date to CrUX metrics (lcp, fid, cls)
        """
        statement = select(TrafficDaily).where(
            TrafficDaily.project_id == project_id,
            TrafficDaily.source_key == "crux",
            TrafficDaily.date >= start_date,
            TrafficDaily.date <= end_date
        )

        results = self.session.exec(statement).all()

        # Build dict of date -> metrics
        crux_dict = {}
        for row in results:
            crux_dict[row.date] = {
                "lcp": row.lcp_p75,
                "fid": row.fid_p75,
                "cls": row.cls_p75,
            }

        return crux_dict

    def import_csv_data(
        self,
        project_id: str | uuid.UUID,
        csv_data: list[dict]
    ) -> int:
        """
        Import traffic data from CSV.

        Create TrafficDaily records with source_key='csv'
        Return count of imported records
        Handle invalid rows gracefully (skip them)

        Args:
            project_id: Project UUID or string UUID
            csv_data: List of dicts with CSV row data

        Returns:
            Count of successfully imported records
        """
        # Convert string to UUID if needed
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)

        imported_count = 0

        for row in csv_data:
            try:
                # Parse date
                date_str = row.get("date")
                if not date_str:
                    continue

                # Handle different date formats
                row_date = date.fromisoformat(date_str)

                # Parse numeric fields (optional)
                sessions = self._parse_int(row.get("sessions"))
                users = self._parse_int(row.get("users"))
                pageviews = self._parse_int(row.get("pageviews"))
                bounce_rate = self._parse_float(row.get("bounce_rate"))
                avg_session_duration = self._parse_float(row.get("avg_session_duration"))

                # Create TrafficDaily record
                traffic_record = TrafficDaily(
                    project_id=project_id,
                    date=row_date,
                    source_key="csv",
                    sessions=sessions,
                    users=users,
                    pageviews=pageviews,
                    bounce_rate=bounce_rate,
                    avg_session_duration=avg_session_duration,
                )

                self.session.add(traffic_record)
                imported_count += 1

            except (ValueError, KeyError, AttributeError):
                # Skip invalid rows
                continue

        # Commit all records
        self.session.commit()

        return imported_count

    def _parse_int(self, value: str | None) -> int | None:
        """Parse string to int, raise ValueError if invalid non-empty value."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            # If value is present but invalid, raise exception to skip the row
            raise ValueError(f"Invalid integer value: {value}") from e

    def _parse_float(self, value: str | None) -> float | None:
        """Parse string to float, raise ValueError if invalid non-empty value."""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError) as e:
            # If value is present but invalid, raise exception to skip the row
            raise ValueError(f"Invalid float value: {value}") from e
