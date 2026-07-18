"""The SQLite engine and session helper.

Sync SQLModel/SQLAlchemy: DB access happens in request-scoped CRUD, which FastAPI
runs in a threadpool, so it never blocks the asyncio loop that runs the OPC UA
subscriptions. `check_same_thread=False` is required because those threadpool threads
differ from the one that created the engine.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

# Import models so SQLModel.metadata knows every table before create_all().
from orchestrion.db import models  # noqa: F401

# Default DB next to the backend; override with ORCHESTRION_DB (tests, deployments,
# or a throwaway instance that must not touch the real database).
DB_PATH = Path(os.environ.get("ORCHESTRION_DB", Path(__file__).resolve().parents[2] / "orchestrion.db"))

_engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables if they do not exist, and apply tiny additive migrations.

    We use create_all rather than a migration tool; create_all never ALTERs an
    existing table, so a column added to a model after a DB already exists must be
    backfilled here. Kept deliberately minimal (add-column-if-missing).
    """
    SQLModel.metadata.create_all(_engine)
    _add_column_if_missing("project", "description", "VARCHAR NOT NULL DEFAULT ''")


def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    with _engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with Session(_engine) as session:
        yield session


def engine():
    """The configured engine (for tests that need to point at a different DB)."""
    return _engine
