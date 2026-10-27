"""Shared test fixtures.

Every test gets a brand-new, empty in-memory SQLite database, so tests never
touch tracker.db and never depend on each other.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# "sqlite://" = in-memory database. StaticPool makes every session share the
# same single connection; otherwise each connection would see its own empty DB.
test_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session():
    """Create all tables before a test and drop them after it."""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session):
    """A TestClient whose requests use the test database instead of the real one."""

    def override_get_db():
        yield db_session

    # Dependency override: wherever a route asks for get_db, give it our session.
    app.dependency_overrides[get_db] = override_get_db
    # Not used as a context manager, so the app's startup (create_all on the
    # real database file) does not run during tests.
    yield TestClient(app)
    app.dependency_overrides.clear()


def days_from_today(days: int) -> str:
    """ISO date string relative to today, e.g. days_from_today(3) -> '2026-10-30'."""
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.fixture
def make_application(client):
    """Factory fixture: create an application through the API and return its JSON."""

    def _make(**fields):
        body = {"company": "Acme Corp", "role": "Software Engineer", **fields}
        response = client.post("/api/applications", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
