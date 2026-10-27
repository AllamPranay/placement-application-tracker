"""Database setup: the engine, the session factory and the Base class for models.

Everything that talks to the database gets a Session from here.
"""

import os
import sqlite3
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# The connection string can be changed without touching code, e.g.
#   DATABASE_URL=postgresql+psycopg://user:pass@host/db   (production)
#   DATABASE_URL=sqlite:////data/tracker.db                (inside Docker)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tracker.db")

# SQLite objects to being used from more than one thread by default, but FastAPI
# runs sync endpoints in a thread pool, so we switch that check off (SQLite only).
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Set SQL_ECHO=1 to print every SQL statement SQLAlchemy sends (great for learning).
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=os.getenv("SQL_ECHO") == "1")

# A "session" is a unit of work: we add/change objects, then commit them together.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent class of every ORM model; it keeps track of all tables."""


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless this PRAGMA is on."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: open one session per request and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
