"""The `Recipe` table — store the MasterRecipe JSON raw, parse on demand; cascade with project."""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from orchestrion.db.models import Project, Recipe
from orchestrion.recipe.model import END, Header, MasterRecipe, RecipeStep, StateReached, Transition


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _master() -> MasterRecipe:
    return MasterRecipe(
        header=Header(name="Batch-42", author="Marwen"),
        formula={"stir_minutes": 5.0},
        steps=[
            RecipeStep(id="s1", pea_id=1, service="Stirring", procedure_id=1, params={"Duration": 300.0}),
            RecipeStep(id="s2", pea_id=2, service="Stirring", procedure_id=2),
        ],
        transitions=[
            Transition(from_ids=["s1"], to_ids=["s2"],
                       condition=StateReached(pea_id=1, service="Stirring", state="COMPLETED")),
            Transition(from_ids=["s2"], to_ids=[END],
                       condition=StateReached(pea_id=2, service="Stirring", state="COMPLETED")),
        ],
    )


def test_recipe_round_trips_through_the_db(session: Session) -> None:
    project = Project(name="Line A")
    session.add(project)
    session.commit()
    session.refresh(project)

    master = _master()
    row = Recipe(project_id=project.id, name="Batch-42", version=1,
                 definition=master.model_dump_json())
    session.add(row)
    session.commit()

    loaded = session.exec(select(Recipe).where(Recipe.name == "Batch-42")).one()
    # The stored definition re-parses losslessly into the same MasterRecipe.
    parsed = MasterRecipe.model_validate_json(loaded.definition)
    assert parsed == master
    assert loaded.project_id == project.id


def test_recipes_read_back_via_project_relationship(session: Session) -> None:
    project = Project(name="Line A")
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(Recipe(project_id=project.id, name="R1", definition=_master().model_dump_json()))
    session.commit()

    session.refresh(project)
    assert [r.name for r in project.recipes] == ["R1"]


def test_deleting_a_project_cascades_to_its_recipes(session: Session) -> None:
    project = Project(name="Line A")
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(Recipe(project_id=project.id, name="R1", definition=_master().model_dump_json()))
    session.commit()

    session.delete(project)
    session.commit()
    assert session.exec(select(Recipe)).all() == []  # gone with the project
