"""
Query clustering service using n-gram overlap.

Clusters related search queries based on word n-gram similarity.
"""

import re
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, col, func, select

from app.models.gsc import GSCQueryDaily, KeywordCluster, KeywordClusterMember


class QueryClusterer:
    """Cluster related queries using n-gram overlap."""

    def __init__(self, session: Session):
        """
        Initialize the query clusterer.

        Args:
            session: SQLModel database session
        """
        self.session = session

    def cluster_queries(
        self,
        project_id: uuid.UUID,
        min_impressions: int = 50,
        period_days: int = 28,
        min_cluster_size: int = 3,
        similarity_threshold: float = 0.5,
    ) -> int:
        """
        Cluster queries based on n-gram overlap.
        Returns number of clusters created.

        Steps:
        1. Get queries with sufficient impressions from GSCQueryDaily
        2. Build n-grams for each query
        3. Find clusters using greedy algorithm with similarity threshold
        4. Filter clusters by min_cluster_size
        5. Delete existing clusters for project
        6. Save new clusters with members

        Args:
            project_id: Project UUID to cluster queries for
            min_impressions: Minimum total impressions required for query
            period_days: Number of days to look back for query data
            min_cluster_size: Minimum number of queries per cluster
            similarity_threshold: Jaccard similarity threshold (0-1)

        Returns:
            Number of clusters created
        """
        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=period_days)

        # Step 1: Get queries with sufficient impressions
        query_stmt: Any = (
            select(
                GSCQueryDaily.query,
                func.sum(GSCQueryDaily.impressions).label("total_impressions"),
            )
            .where(GSCQueryDaily.project_id == project_id)
            .where(GSCQueryDaily.date >= start_date)
            .where(GSCQueryDaily.date <= end_date)
            .group_by(GSCQueryDaily.query)
            .having(func.sum(GSCQueryDaily.impressions) >= min_impressions)
        )

        results = self.session.exec(query_stmt).all()
        queries = [row[0] for row in results]

        if not queries:
            return 0

        # Step 2: Build n-grams for each query
        query_ngrams = {q: self._get_ngrams(q, n_range=(1, 3)) for q in queries}

        # Step 3: Find clusters using greedy algorithm
        clusters = self._find_clusters(queries, query_ngrams, similarity_threshold)

        # Step 4: Filter clusters by min_cluster_size
        filtered_clusters = [c for c in clusters if len(c) >= min_cluster_size]

        # Step 5: Delete existing clusters for project
        # Always delete existing clusters, even if no new clusters will be created
        self._delete_existing_clusters(project_id)

        if not filtered_clusters:
            self.session.commit()
            return 0

        # Step 6: Save new clusters with members
        for cluster_queries in filtered_clusters:
            # Generate cluster label
            label = self._generate_cluster_label(cluster_queries)

            # Get cluster metrics
            metrics = self._get_cluster_metrics(
                project_id, cluster_queries, start_date, end_date
            )

            # Create cluster
            cluster = KeywordCluster(
                project_id=project_id,
                label=label,
                algorithm="ngram",
                total_clicks=metrics["total_clicks"],
                total_impressions=metrics["total_impressions"],
                avg_position=metrics["avg_position"],
                query_count=len(cluster_queries),
            )
            self.session.add(cluster)
            self.session.flush()  # Get cluster ID

            # Add cluster members
            for query in cluster_queries:
                member = KeywordClusterMember(
                    cluster_id=cluster.id,
                    query=query,
                    weight=1.0,  # Could be enhanced with actual similarity score
                )
                self.session.add(member)

        self.session.commit()
        return len(filtered_clusters)

    def _get_ngrams(self, text: str, n_range: tuple[int, int] = (1, 3)) -> set[str]:
        """
        Extract word n-grams from text.
        - Split text into words using regex
        - Generate 1-gram, 2-gram, 3-gram (based on n_range)
        - Return set of ngrams

        Args:
            text: Input text to extract n-grams from
            n_range: Tuple of (min_n, max_n) for n-gram range

        Returns:
            Set of n-gram strings
        """
        if not text:
            return set()

        # Split text into words (alphanumeric sequences)
        # Convert to lowercase for case-insensitive matching
        words = re.findall(r'\b\w+\b', text.lower())

        if not words:
            return set()

        ngrams: set[str] = set()
        min_n, max_n = n_range

        # Generate n-grams for each n in range
        for n in range(min_n, max_n + 1):
            if n > len(words):
                continue

            for i in range(len(words) - n + 1):
                ngram = " ".join(words[i:i + n])
                ngrams.add(ngram)

        return ngrams

    def _jaccard_similarity(self, set1: set[str], set2: set[str]) -> float:
        """
        Calculate Jaccard similarity = |intersection| / |union|.

        Args:
            set1: First set
            set2: Second set

        Returns:
            Jaccard similarity score (0-1)
        """
        if not set1 and not set2:
            return 0.0

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 0.0

        return intersection / union

    def _find_clusters(
        self,
        queries: list[str],
        query_ngrams: dict[str, set[str]],
        threshold: float,
    ) -> list[list[str]]:
        """
        Find clusters using greedy algorithm.
        - For each unassigned query, create new cluster
        - Add similar queries (above threshold) to cluster

        Args:
            queries: List of query strings
            query_ngrams: Dictionary mapping queries to their n-gram sets
            threshold: Similarity threshold for clustering

        Returns:
            List of clusters, where each cluster is a list of query strings
        """
        clusters: list[list[str]] = []
        assigned: set[str] = set()

        for query in queries:
            if query in assigned:
                continue

            # Start new cluster with this query
            cluster = [query]
            assigned.add(query)

            # Find similar queries to add to cluster
            for other_query in queries:
                if other_query in assigned:
                    continue

                similarity = self._jaccard_similarity(
                    query_ngrams[query], query_ngrams[other_query]
                )

                if similarity >= threshold:
                    cluster.append(other_query)
                    assigned.add(other_query)

            clusters.append(cluster)

        return clusters

    def _generate_cluster_label(self, queries: list[str]) -> str:
        """
        Generate label from most common terms.
        - Count word frequency across all queries
        - Return top 3 words joined by space
        - Skip words < 3 chars

        Args:
            queries: List of query strings in the cluster

        Returns:
            Generated cluster label
        """
        word_counts: Counter[str] = Counter()

        for query in queries:
            # Extract words (case-insensitive)
            words = re.findall(r'\b\w+\b', query.lower())
            # Filter words with length >= 3
            filtered_words = [w for w in words if len(w) >= 3]
            word_counts.update(filtered_words)

        # Get top 3 most common words
        top_words = [word for word, _ in word_counts.most_common(3)]

        if not top_words:
            return "Cluster"

        return " ".join(top_words)

    def _get_cluster_metrics(
        self,
        project_id: uuid.UUID,
        queries: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, int | float]:
        """
        Get aggregated metrics (clicks, impressions, position) for queries.

        Args:
            project_id: Project UUID
            queries: List of query strings
            start_date: Start date for metrics
            end_date: End date for metrics

        Returns:
            Dictionary with total_clicks, total_impressions, avg_position
        """
        if not queries:
            return {
                "total_clicks": 0,
                "total_impressions": 0,
                "avg_position": 0.0,
            }

        # Query aggregated metrics
        stmt: Any = (
            select(
                func.sum(GSCQueryDaily.clicks).label("total_clicks"),
                func.sum(GSCQueryDaily.impressions).label("total_impressions"),
                func.avg(GSCQueryDaily.position).label("avg_position"),
            )
            .where(GSCQueryDaily.project_id == project_id)
            .where(col(GSCQueryDaily.query).in_(tuple(queries)))
            .where(GSCQueryDaily.date >= start_date)
            .where(GSCQueryDaily.date <= end_date)
        )

        result = self.session.exec(stmt).first()

        if not result or result[0] is None:
            return {
                "total_clicks": 0,
                "total_impressions": 0,
                "avg_position": 0.0,
            }

        return {
            "total_clicks": int(result[0] or 0),
            "total_impressions": int(result[1] or 0),
            "avg_position": float(result[2] or 0.0),
        }

    def _delete_existing_clusters(self, project_id: uuid.UUID) -> None:
        """
        Delete existing clusters for project.

        Args:
            project_id: Project UUID
        """
        # Delete clusters (members will cascade delete)
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(KeywordCluster).where(
            col(KeywordCluster.project_id) == project_id
        )
        self.session.exec(stmt)  # type: ignore[call-overload]
        # Don't commit here - let the caller commit after adding new clusters
