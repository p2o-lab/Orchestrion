"""The SQLite engine and session helper.

Sync SQLModel/SQLAlchemy: DB access happens in request-scoped CRUD, which FastAPI
runs in a threadpool, so it never blocks the asyncio loop that runs the OPC UA
subscriptions. `check_same_thread=False` is required because those threadpool threads
differ from the one that created the engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# Import models so SQLModel.metadata knows every table before create_all().
from orchestrion.db import models  # noqa: F401

DB_PATH = Path(__file__).resolve().parents[2] / "orchestrion.db"

_engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables if they do not exist. Called once at app startup."""
    SQLModel.metadata.create_all(_engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with Session(_engine) as session:
        yield session


def engine():
    """The configured engine (for tests that need to point at a different DB)."""
    return _engine
