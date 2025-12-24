"""Tests for TransparencyService."""

import pytest
from datetime import date, timedelta
from sqlmodel import Session

from app.models.ads import TransparencyCreative
from app.services.ads.transparency import TransparencyService


def test_fetch_competitor_ads(db: Session) -> None:
    """Test fetching competitor ads (stub implementation)."""
    service = TransparencyService(db)

    ads = service.fetch_competitor_ads(
        advertiser_name="Test Competitor",
        source="google_ads_transparency",
        limit=5,
    )

    # Should return mock data
    assert len(ads) > 0
    assert len(ads) <= 5

    # Verify structure
    ad = ads[0]
    assert "advertiser_id" in ad
    assert "advertiser_name" in ad
    assert "creative_id" in ad
    assert "headline" in ad
    assert "description" in ad
    assert ad["advertiser_name"] == "Test Competitor"


def test_store_creatives(db: Session) -> None:
    """Test storing ad creatives in database."""
    service = TransparencyService(db)

    # Create sample creatives
    creatives = [
        {
            "advertiser_id": "test_advertiser_001",
            "advertiser_name": "Test Advertiser",
            "creative_id": "creative_001",
            "headline": "Test Headline",
            "description": "Test description",
            "image_url": "https://example.com/image.jpg",
            "landing_url": "https://example.com/landing",
            "first_seen": date.today() - timedelta(days=7),
            "last_seen": date.today(),
            "geo_targeting": ["US", "CA"],
            "metadata": {"platform": "search"},
        }
    ]

    stored_count = service.store_creatives(
        creatives=creatives,
        source_key="google_ads_transparency",
    )

    assert stored_count == 1

    # Verify it was stored
    retrieved = service.get_creatives_by_advertiser("Test Advertiser")
    assert len(retrieved) == 1
    assert retrieved[0].headline == "Test Headline"
    assert retrieved[0].source_key == "google_ads_transparency"


def test_store_creatives_update_existing(db: Session) -> None:
    """Test updating existing creative when storing duplicates."""
    service = TransparencyService(db)

    # Store initial creative
    creative_data = {
        "advertiser_id": "test_advertiser_002",
        "advertiser_name": "Update Test",
        "creative_id": "creative_002",
        "headline": "Original Headline",
        "description": "Original description",
        "first_seen": date.today() - timedelta(days=14),
        "last_seen": date.today() - timedelta(days=7),
        "geo_targeting": ["US"],
        "metadata": {},
    }

    service.store_creatives([creative_data], "google_ads_transparency")

    # Update with new data
    creative_data["headline"] = "Updated Headline"
    creative_data["last_seen"] = date.today()
    creative_data["geo_targeting"] = ["US", "CA", "UK"]

    stored_count = service.store_creatives([creative_data], "google_ads_transparency")

    assert stored_count == 1

    # Should still have only one creative, but updated
    retrieved = service.get_creatives_by_advertiser("Update Test")
    assert len(retrieved) == 1
    assert retrieved[0].headline == "Updated Headline"
    assert retrieved[0].last_seen == date.today()
    assert set(retrieved[0].geo_targeting) == {"US", "CA", "UK"}


def test_get_creatives_by_advertiser(db: Session) -> None:
    """Test retrieving creatives by advertiser name."""
    service = TransparencyService(db)

    # Store multiple creatives
    creatives = [
        {
            "advertiser_id": "advertiser_a",
            "advertiser_name": "Advertiser A",
            "creative_id": f"creative_a_{i}",
            "headline": f"Headline {i}",
            "description": "Description",
            "first_seen": date.today(),
            "last_seen": date.today(),
            "geo_targeting": [],
            "metadata": {},
        }
        for i in range(3)
    ]

    service.store_creatives(creatives, "google_ads_transparency")

    # Retrieve by advertiser
    retrieved = service.get_creatives_by_advertiser("Advertiser A")
    assert len(retrieved) == 3

    # Test partial match
    retrieved_partial = service.get_creatives_by_advertiser("Advertiser")
    assert len(retrieved_partial) == 3


def test_get_recent_creatives(db: Session) -> None:
    """Test retrieving recently seen creatives."""
    service = TransparencyService(db)

    # Store old and new creatives
    old_creative = {
        "advertiser_id": "old_advertiser",
        "advertiser_name": "Old Advertiser",
        "creative_id": "old_creative",
        "headline": "Old Headline",
        "description": "Description",
        "first_seen": date.today() - timedelta(days=60),
        "last_seen": date.today() - timedelta(days=45),
        "geo_targeting": [],
        "metadata": {},
    }

    recent_creative = {
        "advertiser_id": "recent_advertiser",
        "advertiser_name": "Recent Advertiser",
        "creative_id": "recent_creative",
        "headline": "Recent Headline",
        "description": "Description",
        "first_seen": date.today() - timedelta(days=5),
        "last_seen": date.today(),
        "geo_targeting": [],
        "metadata": {},
    }

    service.store_creatives([old_creative], "google_ads_transparency")
    service.store_creatives([recent_creative], "google_ads_transparency")

    # Get creatives from last 30 days
    recent = service.get_recent_creatives(days=30)
    assert len(recent) == 1
    assert recent[0].headline == "Recent Headline"

    # Get creatives from last 90 days
    all_recent = service.get_recent_creatives(days=90)
    assert len(all_recent) == 2


def test_sync_competitor_ads(db: Session) -> None:
    """Test syncing competitor ads (fetch + store)."""
    service = TransparencyService(db)

    result = service.sync_competitor_ads(
        advertiser_name="Sync Test Competitor",
        source_key="google_ads_transparency",
    )

    # Verify result structure
    assert "fetched" in result
    assert "stored" in result
    assert "advertiser" in result
    assert "source" in result

    assert result["fetched"] > 0
    assert result["stored"] == result["fetched"]
    assert result["advertiser"] == "Sync Test Competitor"
    assert result["source"] == "google_ads_transparency"

    # Verify data was stored
    retrieved = service.get_creatives_by_advertiser("Sync Test Competitor")
    assert len(retrieved) > 0
