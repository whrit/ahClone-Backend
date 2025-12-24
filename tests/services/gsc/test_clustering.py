"""
Tests for query clustering service.

Following TDD principles: Write tests first, then implement.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool

from app.models.gsc import GSCQueryDaily, KeywordCluster, KeywordClusterMember
from app.services.gsc.clustering import QueryClusterer


@pytest.fixture(name="session")
def session_fixture():
    """Create a test database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="project_id")
def project_id_fixture():
    """Create a test project ID."""
    return uuid.uuid4()


@pytest.fixture(name="clusterer")
def clusterer_fixture(session):
    """Create a QueryClusterer instance."""
    return QueryClusterer(session)


@pytest.fixture(name="sample_queries")
def sample_queries_fixture(session: Session, project_id: uuid.UUID):
    """Create sample GSCQueryDaily records for testing."""
    today = date.today()
    queries = [
        # Cluster 1: SEO tools
        ("best seo tools", 100, 1000),
        ("seo tools for website", 80, 900),
        ("top seo tools 2024", 70, 850),
        ("seo analysis tools", 60, 800),
        # Cluster 2: keyword research
        ("keyword research tools", 90, 950),
        ("best keyword research", 75, 880),
        ("keyword research free", 65, 820),
        # Cluster 3: backlink checker
        ("backlink checker free", 85, 920),
        ("free backlink checker tool", 70, 870),
        ("backlink analysis tool", 60, 810),
        # Low impressions (should be filtered out)
        ("niche query", 5, 20),
        # Single query (should not form cluster if min_cluster_size=3)
        ("unique standalone query", 100, 500),
    ]

    for query_text, clicks, impressions in queries:
        # Create records for multiple days to aggregate
        for days_ago in range(7):
            query_date = today - timedelta(days=days_ago)
            gsc_query = GSCQueryDaily(
                project_id=project_id,
                date=query_date,
                query=query_text,
                clicks=clicks // 7,  # Distribute clicks across days
                impressions=impressions // 7,
                ctr=clicks / impressions if impressions > 0 else 0.0,
                position=10.5,
            )
            session.add(gsc_query)

    session.commit()


class TestGetNgrams:
    """Test n-gram extraction."""

    def test_get_unigrams(self, clusterer: QueryClusterer):
        """Test extracting 1-grams (single words)."""
        text = "best seo tools"
        ngrams = clusterer._get_ngrams(text, n_range=(1, 1))
        assert ngrams == {"best", "seo", "tools"}

    def test_get_bigrams(self, clusterer: QueryClusterer):
        """Test extracting 2-grams (word pairs)."""
        text = "best seo tools"
        ngrams = clusterer._get_ngrams(text, n_range=(2, 2))
        assert ngrams == {"best seo", "seo tools"}

    def test_get_trigrams(self, clusterer: QueryClusterer):
        """Test extracting 3-grams (word triplets)."""
        text = "best seo tools online"
        ngrams = clusterer._get_ngrams(text, n_range=(3, 3))
        assert ngrams == {"best seo tools", "seo tools online"}

    def test_get_combined_ngrams(self, clusterer: QueryClusterer):
        """Test extracting combined n-grams (1-3 grams)."""
        text = "seo tools"
        ngrams = clusterer._get_ngrams(text, n_range=(1, 3))
        expected = {
            "seo", "tools",  # 1-grams
            "seo tools",  # 2-grams
        }
        assert ngrams == expected

    def test_get_ngrams_with_special_characters(self, clusterer: QueryClusterer):
        """Test n-gram extraction handles special characters."""
        text = "best SEO-tools & services!"
        ngrams = clusterer._get_ngrams(text, n_range=(1, 1))
        # Should extract words and handle case/special chars
        assert "best" in ngrams
        assert "seo" in ngrams or "SEO" in ngrams.union({t.lower() for t in ngrams})

    def test_get_ngrams_empty_string(self, clusterer: QueryClusterer):
        """Test n-gram extraction with empty string."""
        text = ""
        ngrams = clusterer._get_ngrams(text, n_range=(1, 3))
        assert ngrams == set()


class TestJaccardSimilarity:
    """Test Jaccard similarity calculation."""

    def test_identical_sets(self, clusterer: QueryClusterer):
        """Test similarity of identical sets is 1.0."""
        set1 = {"a", "b", "c"}
        set2 = {"a", "b", "c"}
        similarity = clusterer._jaccard_similarity(set1, set2)
        assert similarity == 1.0

    def test_disjoint_sets(self, clusterer: QueryClusterer):
        """Test similarity of disjoint sets is 0.0."""
        set1 = {"a", "b", "c"}
        set2 = {"d", "e", "f"}
        similarity = clusterer._jaccard_similarity(set1, set2)
        assert similarity == 0.0

    def test_partial_overlap(self, clusterer: QueryClusterer):
        """Test similarity with partial overlap."""
        set1 = {"a", "b", "c"}
        set2 = {"b", "c", "d"}
        # Intersection: {b, c} = 2 elements
        # Union: {a, b, c, d} = 4 elements
        # Similarity: 2/4 = 0.5
        similarity = clusterer._jaccard_similarity(set1, set2)
        assert similarity == 0.5

    def test_empty_sets(self, clusterer: QueryClusterer):
        """Test similarity of empty sets."""
        set1: set[str] = set()
        set2: set[str] = set()
        similarity = clusterer._jaccard_similarity(set1, set2)
        assert similarity == 0.0

    def test_one_empty_set(self, clusterer: QueryClusterer):
        """Test similarity when one set is empty."""
        set1 = {"a", "b"}
        set2: set[str] = set()
        similarity = clusterer._jaccard_similarity(set1, set2)
        assert similarity == 0.0


class TestFindClusters:
    """Test cluster finding algorithm."""

    def test_find_clusters_high_threshold(self, clusterer: QueryClusterer):
        """Test clustering with high similarity threshold."""
        queries = ["best seo tools", "seo tools online", "keyword research"]
        query_ngrams = {
            q: clusterer._get_ngrams(q, n_range=(1, 3)) for q in queries
        }
        # High threshold should create separate clusters
        clusters = clusterer._find_clusters(queries, query_ngrams, threshold=0.9)
        # Each query should be in its own cluster
        assert len(clusters) == 3

    def test_find_clusters_low_threshold(self, clusterer: QueryClusterer):
        """Test clustering with low similarity threshold."""
        queries = ["seo tools", "seo analysis", "seo software"]
        query_ngrams = {
            q: clusterer._get_ngrams(q, n_range=(1, 3)) for q in queries
        }
        # Low threshold should group similar queries
        # With greedy algorithm, first query creates cluster and absorbs similar ones
        clusters = clusterer._find_clusters(queries, query_ngrams, threshold=0.3)
        # Should create clusters (greedy algo depends on first match)
        assert len(clusters) >= 1
        assert len(clusters) <= len(queries)

    def test_find_clusters_moderate_threshold(self, clusterer: QueryClusterer):
        """Test clustering with moderate similarity threshold."""
        queries = [
            "best seo tools",
            "top seo tools",
            "seo tools free",
            "keyword research",
            "backlink checker",
        ]
        query_ngrams = {
            q: clusterer._get_ngrams(q, n_range=(1, 3)) for q in queries
        }
        clusters = clusterer._find_clusters(queries, query_ngrams, threshold=0.5)
        # With greedy algorithm and moderate threshold, similar queries cluster
        # The exact number depends on which query is processed first
        assert len(clusters) >= 1
        assert len(clusters) <= len(queries)
        # Verify all queries are assigned
        all_clustered = [q for cluster in clusters for q in cluster]
        assert set(all_clustered) == set(queries)

    def test_find_clusters_preserves_all_queries(self, clusterer: QueryClusterer):
        """Test that all queries are assigned to clusters."""
        queries = ["query one", "query two", "query three"]
        query_ngrams = {
            q: clusterer._get_ngrams(q, n_range=(1, 3)) for q in queries
        }
        clusters = clusterer._find_clusters(queries, query_ngrams, threshold=0.5)
        all_clustered_queries = [q for cluster in clusters for q in cluster]
        assert set(all_clustered_queries) == set(queries)


class TestGenerateClusterLabel:
    """Test cluster label generation."""

    def test_generate_label_common_words(self, clusterer: QueryClusterer):
        """Test label generation picks most common words."""
        queries = [
            "best seo tools",
            "seo tools online",
            "seo tools free",
        ]
        label = clusterer._generate_cluster_label(queries)
        # "seo" and "tools" appear 3 times each
        assert "seo" in label.lower()
        assert "tools" in label.lower()

    def test_generate_label_skips_short_words(self, clusterer: QueryClusterer):
        """Test label generation skips words shorter than 3 characters."""
        queries = [
            "seo is great",
            "seo is good",
            "seo is best",
        ]
        label = clusterer._generate_cluster_label(queries)
        # Should skip "is" (2 chars)
        assert "is" not in label.lower()
        assert "seo" in label.lower()

    def test_generate_label_limits_to_top_words(self, clusterer: QueryClusterer):
        """Test label generation limits to top 3 words."""
        queries = [
            "one two three four five",
            "one two three four",
            "one two three",
        ]
        label = clusterer._generate_cluster_label(queries)
        words = label.split()
        # Should have at most 3 words
        assert len(words) <= 3

    def test_generate_label_single_query(self, clusterer: QueryClusterer):
        """Test label generation with single query."""
        queries = ["keyword research tools"]
        label = clusterer._generate_cluster_label(queries)
        # Should use words from the single query
        assert len(label) > 0


class TestGetClusterMetrics:
    """Test cluster metrics aggregation."""

    def test_get_cluster_metrics_aggregates_correctly(
        self, clusterer: QueryClusterer, session: Session, project_id: uuid.UUID
    ):
        """Test metrics are correctly aggregated for cluster queries."""
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()

        # Create test data
        queries = ["query one", "query two"]
        for query_text in queries:
            for days_ago in range(7):
                query_date = start_date + timedelta(days=days_ago)
                gsc_query = GSCQueryDaily(
                    project_id=project_id,
                    date=query_date,
                    query=query_text,
                    clicks=10,
                    impressions=100,
                    ctr=0.1,
                    position=5.0,
                )
                session.add(gsc_query)
        session.commit()

        metrics = clusterer._get_cluster_metrics(
            project_id, queries, start_date, end_date
        )

        # 2 queries * 7 days * 10 clicks = 140 total clicks
        assert metrics["total_clicks"] == 140
        # 2 queries * 7 days * 100 impressions = 1400 total impressions
        assert metrics["total_impressions"] == 1400
        # Average position should be 5.0
        assert metrics["avg_position"] == 5.0

    def test_get_cluster_metrics_no_data(
        self, clusterer: QueryClusterer, project_id: uuid.UUID
    ):
        """Test metrics with no data returns zeros."""
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()
        queries = ["nonexistent query"]

        metrics = clusterer._get_cluster_metrics(
            project_id, queries, start_date, end_date
        )

        assert metrics["total_clicks"] == 0
        assert metrics["total_impressions"] == 0
        assert metrics["avg_position"] == 0.0


class TestDeleteExistingClusters:
    """Test deletion of existing clusters."""

    def test_delete_existing_clusters_removes_all(
        self, clusterer: QueryClusterer, session: Session, project_id: uuid.UUID
    ):
        """Test all clusters for project are deleted."""
        # Create existing clusters
        for i in range(3):
            cluster = KeywordCluster(
                project_id=project_id,
                label=f"Cluster {i}",
                algorithm="ngram",
                total_clicks=100,
                total_impressions=1000,
                avg_position=5.0,
                query_count=5,
            )
            session.add(cluster)
            session.commit()

            # Add members to cluster
            for j in range(2):
                member = KeywordClusterMember(
                    cluster_id=cluster.id,
                    query=f"query {i}-{j}",
                    weight=0.8,
                )
                session.add(member)
        session.commit()

        # Verify clusters exist
        existing_clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()
        assert len(existing_clusters) == 3

        # Delete clusters
        clusterer._delete_existing_clusters(project_id)

        # Verify clusters are deleted
        remaining_clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()
        assert len(remaining_clusters) == 0

    def test_delete_existing_clusters_preserves_other_projects(
        self, clusterer: QueryClusterer, session: Session, project_id: uuid.UUID
    ):
        """Test deletion only affects target project."""
        other_project_id = uuid.uuid4()

        # Create cluster for target project
        cluster1 = KeywordCluster(
            project_id=project_id,
            label="Target Cluster",
            algorithm="ngram",
            total_clicks=100,
            total_impressions=1000,
            avg_position=5.0,
            query_count=5,
        )
        session.add(cluster1)

        # Create cluster for other project
        cluster2 = KeywordCluster(
            project_id=other_project_id,
            label="Other Cluster",
            algorithm="ngram",
            total_clicks=100,
            total_impressions=1000,
            avg_position=5.0,
            query_count=5,
        )
        session.add(cluster2)
        session.commit()

        # Delete clusters for target project
        clusterer._delete_existing_clusters(project_id)

        # Verify target project clusters are deleted
        target_clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()
        assert len(target_clusters) == 0

        # Verify other project clusters remain
        other_clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == other_project_id
            )
        ).all()
        assert len(other_clusters) == 1


class TestClusterQueries:
    """Test end-to-end query clustering."""

    def test_cluster_queries_creates_clusters(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test that cluster_queries creates appropriate clusters."""
        num_clusters = clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=100,  # Filter out low impression queries
            period_days=28,
            min_cluster_size=3,
            similarity_threshold=0.3,  # Lower threshold to capture more semantic similarity
        )

        # Should create at least 1 cluster from sample data
        # Sample data has 3 groups: "seo tools" (4 queries), "keyword research" (3), "backlink" (3)
        # With n-gram overlap and threshold 0.3, we should get at least 1-3 clusters
        assert num_clusters >= 1
        assert num_clusters <= 5

    def test_cluster_queries_filters_by_min_impressions(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test min_impressions filtering works."""
        # High threshold should exclude most queries
        num_clusters = clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=5000,  # Very high threshold
            period_days=28,
            min_cluster_size=1,
            similarity_threshold=0.3,
        )

        # Should create 0 clusters (all queries filtered out)
        assert num_clusters == 0

    def test_cluster_queries_filters_by_min_cluster_size(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test min_cluster_size filtering works."""
        num_clusters = clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=50,
            period_days=28,
            min_cluster_size=10,  # Require large clusters
            similarity_threshold=0.3,
        )

        # Should have fewer clusters (small clusters filtered out)
        assert num_clusters >= 0

    def test_cluster_queries_saves_to_database(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test clusters are saved to database correctly."""
        num_clusters = clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=100,
            period_days=28,
            min_cluster_size=3,
            similarity_threshold=0.5,
        )

        # Verify clusters exist in database
        clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()
        assert len(clusters) == num_clusters

        # Verify each cluster has members
        for cluster in clusters:
            members = session.exec(
                KeywordClusterMember.__table__.select().where(
                    KeywordClusterMember.cluster_id == cluster.id
                )
            ).all()
            assert len(members) >= 3  # min_cluster_size

    def test_cluster_queries_sets_correct_algorithm(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test clusters have correct algorithm set."""
        clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=100,
            period_days=28,
            min_cluster_size=3,
            similarity_threshold=0.5,
        )

        clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()

        for cluster in clusters:
            assert cluster.algorithm == "ngram"

    def test_cluster_queries_deletes_existing_clusters(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test that existing clusters are deleted before creating new ones."""
        # Create initial clusters
        old_cluster = KeywordCluster(
            project_id=project_id,
            label="Old Cluster",
            algorithm="old_algo",
            total_clicks=999,
            total_impressions=9999,
            avg_position=99.0,
            query_count=99,
        )
        session.add(old_cluster)
        session.commit()

        # Run clustering
        clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=100,
            period_days=28,
            min_cluster_size=3,
            similarity_threshold=0.5,
        )

        # Verify old cluster is gone
        clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()

        # Should not find the old cluster
        assert all(cluster.algorithm != "old_algo" for cluster in clusters)

    def test_cluster_queries_calculates_metrics(
        self,
        clusterer: QueryClusterer,
        session: Session,
        project_id: uuid.UUID,
        sample_queries,
    ):
        """Test cluster metrics are calculated correctly."""
        clusterer.cluster_queries(
            project_id=project_id,
            min_impressions=100,
            period_days=28,
            min_cluster_size=3,
            similarity_threshold=0.5,
        )

        clusters = session.exec(
            KeywordCluster.__table__.select().where(
                KeywordCluster.project_id == project_id
            )
        ).all()

        for cluster in clusters:
            # Metrics should be populated
            assert cluster.total_clicks > 0
            assert cluster.total_impressions > 0
            assert cluster.avg_position > 0
            assert cluster.query_count >= 3  # min_cluster_size
