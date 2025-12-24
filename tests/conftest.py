from collections.abc import Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import crud
from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import IntegrationAccount, Item, JobRun, Project, User
from app.models.serp import KeywordTarget, RankObservation, SerpSnapshot
from app.models.links import AnchorAgg, BacklinkEdge, LinkSnapshot, RefDomainAgg
from app.models.gsc import GSCQueryDaily, GSCPageDaily, KeywordClusterMember, KeywordCluster, GSCProperty
from app.models.audit import AuditIssue, AuditLinkEdge, CrawledPage, AuditRun
from app.models.ads import AdsAccount, AdsCampaignDaily, AdsKeywordDaily, TransparencyCreative, TrafficDaily
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def setup_encryption_key() -> Generator[None, None, None]:
    """Set TOKEN_ENCRYPTION_KEY for tests if not already set"""
    if not settings.TOKEN_ENCRYPTION_KEY:
        # Generate a test encryption key
        settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    yield


@pytest.fixture(scope="session", autouse=True)
def _db_session() -> Generator[Session, None, None]:
    """Session-scoped database session for initialization."""
    with Session(engine) as session:
        init_db(session)
        yield session
        # Final cleanup at end of test session
        # Delete in order to respect foreign key constraints
        session.exec(delete(BacklinkEdge))
        session.exec(delete(RefDomainAgg))
        session.exec(delete(AnchorAgg))
        session.exec(delete(LinkSnapshot))
        session.exec(delete(RankObservation))
        session.exec(delete(SerpSnapshot))
        session.exec(delete(KeywordTarget))
        session.exec(delete(GSCQueryDaily))
        session.exec(delete(GSCPageDaily))
        session.exec(delete(KeywordClusterMember))
        session.exec(delete(KeywordCluster))
        session.exec(delete(GSCProperty))
        session.exec(delete(AuditIssue))
        session.exec(delete(AuditLinkEdge))
        session.exec(delete(CrawledPage))
        session.exec(delete(AuditRun))
        session.exec(delete(AdsCampaignDaily))
        session.exec(delete(AdsKeywordDaily))
        session.exec(delete(TrafficDaily))
        session.exec(delete(AdsAccount))
        session.exec(delete(TransparencyCreative))
        session.exec(delete(JobRun))
        session.exec(delete(IntegrationAccount))
        session.exec(delete(Project))
        session.exec(delete(Item))
        session.exec(delete(User))
        session.commit()


@pytest.fixture(scope="function")
def db(_db_session: Session) -> Generator[Session, None, None]:
    """Function-scoped database session that cleans up all tables after each test."""
    yield _db_session

    # Rollback any pending transaction (in case test left session in bad state)
    _db_session.rollback()

    # Cleanup all tables after each test (child tables first to respect FK constraints)
    # Links tables
    _db_session.exec(delete(BacklinkEdge))
    _db_session.exec(delete(RefDomainAgg))
    _db_session.exec(delete(AnchorAgg))
    _db_session.exec(delete(LinkSnapshot))

    # SERP tables
    _db_session.exec(delete(RankObservation))
    _db_session.exec(delete(SerpSnapshot))
    _db_session.exec(delete(KeywordTarget))

    # GSC tables
    _db_session.exec(delete(GSCQueryDaily))
    _db_session.exec(delete(GSCPageDaily))
    _db_session.exec(delete(KeywordClusterMember))
    _db_session.exec(delete(KeywordCluster))
    _db_session.exec(delete(GSCProperty))

    # Audit tables
    _db_session.exec(delete(AuditIssue))
    _db_session.exec(delete(AuditLinkEdge))
    _db_session.exec(delete(CrawledPage))
    _db_session.exec(delete(AuditRun))

    # Ads tables
    _db_session.exec(delete(AdsCampaignDaily))
    _db_session.exec(delete(AdsKeywordDaily))
    _db_session.exec(delete(TrafficDaily))
    _db_session.exec(delete(AdsAccount))
    _db_session.exec(delete(TransparencyCreative))

    # Other tables
    _db_session.exec(delete(JobRun))
    _db_session.exec(delete(IntegrationAccount))
    _db_session.exec(delete(Project))
    _db_session.exec(delete(Item))

    _db_session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, _db_session: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=_db_session
    )


@pytest.fixture(scope="module")
def normal_user(_db_session: Session) -> User:
    user = crud.get_user_by_email(session=_db_session, email=settings.EMAIL_TEST_USER)
    assert user is not None
    return user
