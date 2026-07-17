"""Project/Pea persistence — CRUD and cascade, against an in-memory SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from orchestrion.db.models import Pea, Project


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,          # one shared in-memory connection
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _pea(project_id, name):
    return Pea(
        project_id=project_id,
        name=name,
        aml_filename=f"{name}.aml",
        aml_content="<CAEXFile/>",
        endpoint_url="opc.tcp://127.0.0.1:48050",
    )


def test_create_project_and_pea(session):
    project = Project(name="Reactor Line A")
    session.add(project)
    session.commit()
    session.refresh(project)
    assert project.id is not None

    session.add(_pea(project.id, "Stirrer"))
    session.commit()

    fetched = session.get(Project, project.id)
    assert [p.name for p in fetched.peas] == ["Stirrer"]


def test_pea_carries_its_aml_and_endpoint(session):
    project = Project(name="P")
    session.add(project)
    session.commit()
    session.add(_pea(project.id, "HC30"))
    session.commit()

    pea = session.exec(select(Pea)).one()
    assert pea.aml_content == "<CAEXFile/>"
    assert pea.endpoint_url == "opc.tcp://127.0.0.1:48050"
    assert pea.project_id == project.id


def test_deleting_a_project_cascades_to_its_peas(session):
    project = Project(name="P")
    session.add(project)
    session.commit()
    session.add_all([_pea(project.id, "A"), _pea(project.id, "B")])
    session.commit()

    session.delete(project)
    session.commit()

    assert session.exec(select(Pea)).all() == []
    assert session.exec(select(Project)).all() == []
