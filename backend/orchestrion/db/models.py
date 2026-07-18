"""Database tables — a workspace of projects, each holding imported PEAs.

Only *valid* MTPs are stored: import parses and validates first, and rejects a bad
file before it ever reaches a row (so every `Pea` here is known-parseable). The raw
`.aml` is kept as text — the parsed model is re-derived on demand via `read_mtp`, so
there is nothing to keep in sync and a backup is just the .db file.
"""

from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel

# NOTE: deliberately no `from __future__ import annotations` — SQLModel resolves
# Relationship() target types from real annotations at class-definition time, and the
# stringised annotations that future-import produces break `list["Pea"]` mapping.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    """A modular plant / plant configuration — the top level of the workspace."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)

    peas: list["Pea"] = Relationship(
        back_populates="project",
        # Deleting a project removes its PEAs (they cannot exist without one).
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Pea(SQLModel, table=True):
    """One imported MTP, scoped to a project. `name` is the user's label."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str

    aml_filename: str
    """The uploaded file's name — shown to the user, and used for parser messages."""

    aml_content: str
    """The raw MTP `.aml` XML. The single source of truth; re-parsed on demand."""

    endpoint_url: str
    """Cached from the parse at import — the OPC UA endpoint, for quick display."""

    created_at: datetime = Field(default_factory=_utcnow)

    project: Project | None = Relationship(back_populates="peas")
