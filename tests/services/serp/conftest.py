"""
Conftest for SERP service tests.

These tests don't require database fixtures, so we override the session-level
db fixture to prevent model initialization errors.
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def db():
    """Override the global db fixture for SERP tests that don't need database."""
    # Return None - these tests don't use the database
    yield None
