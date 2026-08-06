"""Recipe CRUD, scoped to a project.

A recipe is the master recipe an operator authors ([IEC 61512-1 §6.2]); its `MasterRecipe`
JSON is stored raw and re-parsed on demand (like a PEA's `.aml`). Create/update is the gate:
FastAPI validates the `MasterRecipe` structurally (Pydantic — unique ids, transitions resolve),
then this layer validates every step and condition against the project's **actual** parsed PEAs
(the pure model cannot — it does not know the PEAs). A bad reference is rejected with HTTP 422.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrion.api.mtp_import import parse_aml
from orchestrion.db.engine import get_session
from orchestrion.db.models import Pea, Project, Recipe
from orchestrion.mtp.model import Pea as PeaModel
from orchestrion.recipe.model import (
    Always, And, Condition, Elapsed, MasterRecipe, Or, StateReached, ValueThreshold,
)
from orchestrion.state.codes import ServiceState

router = APIRouter(tags=["recipes"])


class RecipeSummary(BaseModel):
    id: int
    project_id: int
    name: str
    version: int
    step_count: int
    created_at: datetime


class RecipeDetail(RecipeSummary):
    definition: MasterRecipe


def _summary(row: Recipe, recipe: MasterRecipe) -> RecipeSummary:
    return RecipeSummary(
        id=row.id, project_id=row.project_id, name=row.name,
        version=row.version, step_count=len(recipe.steps), created_at=row.created_at,
    )


def _project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project


def _row_or_404(session: Session, project_id: int, recipe_id: int) -> Recipe:
    row = session.get(Recipe, recipe_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"recipe {recipe_id} not found in project {project_id}")
    return row


def _project_peas(session: Session, project_id: int) -> dict[int, PeaModel]:
    """The project's PEAs as parsed models, keyed by DB id — the ground truth a recipe's
    step/condition references are checked against."""
    rows = session.exec(select(Pea).where(Pea.project_id == project_id)).all()
    return {r.id: parse_aml(r.aml_content.encode("utf-8"), r.aml_filename) for r in rows}


def _require_service(peas: dict[int, PeaModel], pea_id: int, service: str, where: str) -> PeaModel:
    pea = peas.get(pea_id)
    if pea is None:
        raise HTTPException(422, f"{where}: PEA {pea_id} is not in this project")
    if not any(s.name == service for s in pea.services):
        raise HTTPException(422, f"{where}: service {service!r} not on PEA {pea_id}")
    return pea


def _value_names(pea: PeaModel) -> set[str]:
    """Every value TagName the PEA publishes — the keys the live snapshot uses (mirrors the set
    the connection subscribes: PEA-wide process values + per-service config + per-procedure)."""
    names = {v.name for v in (*pea.process_values_in, *pea.process_values_out)}
    for service in pea.services:
        names |= {v.name for v in service.config_parameters}
        for proc in service.procedures:
            names |= {v.name for v in (*proc.report_values, *proc.process_values_in, *proc.process_values_out)}
    return names


def _check_condition(cond: Condition, peas: dict[int, PeaModel], where: str) -> None:
    """Recursively validate a transition condition tree against the project's PEAs."""
    if isinstance(cond, StateReached):
        _require_service(peas, cond.pea_id, cond.service, where)
        if cond.state not in ServiceState.__members__:
            raise HTTPException(
                422, f"{where}: {cond.state!r} is not a [2658-4 Table 14] state "
                f"(one of {list(ServiceState.__members__)})",
            )
    elif isinstance(cond, ValueThreshold):
        pea = peas.get(cond.pea_id)
        if pea is None:
            raise HTTPException(422, f"{where}: PEA {cond.pea_id} is not in this project")
        if cond.value_name not in _value_names(pea):
            raise HTTPException(422, f"{where}: value {cond.value_name!r} not on PEA {cond.pea_id}")
    elif isinstance(cond, (Always, Elapsed)):
        # Nothing to resolve: neither references the plant. `Always` would otherwise fall
        # through this chain unnamed, which reads as an oversight rather than a decision.
        # TODO(unit 7): reject `Always` on a transition whose from_ids include a *continuous*
        # step — there the receptivity IS the completion criterion, so it would start the
        # service and complete it in the same instant (chart §4).
        pass
    elif isinstance(cond, (And, Or)):
        for sub in cond.conditions:
            _check_condition(sub, peas, where)


def _validate_against_project(recipe: MasterRecipe, peas: dict[int, PeaModel]) -> None:
    """Reject a recipe whose steps/conditions reference a PEA/service/procedure/value/state that
    does not exist in this project (HTTP 422). The pure model only checks internal structure."""
    for step in recipe.steps:
        where = f"step {step.id!r}"
        pea = _require_service(peas, step.pea_id, step.service, where)
        service = next(s for s in pea.services if s.name == step.service)
        if not any(p.procedure_id == step.procedure_id for p in service.procedures):
            raise HTTPException(422, f"{where}: procedure {step.procedure_id} not on service {step.service!r}")

    for t in recipe.transitions:
        _check_condition(t.condition, peas, f"transition {t.from_ids}->{t.to_ids}")


@router.post("/api/projects/{project_id}/recipes", response_model=RecipeSummary, status_code=201,
             responses={422: {"description": "the recipe references an unknown PEA/service/procedure/state"}})
def create_recipe(
    project_id: int, body: MasterRecipe, session: Session = Depends(get_session)
) -> RecipeSummary:
    _project_or_404(session, project_id)
    _validate_against_project(body, _project_peas(session, project_id))
    row = Recipe(
        project_id=project_id, name=body.header.name, version=body.header.version,
        definition=body.model_dump_json(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _summary(row, body)


@router.get("/api/projects/{project_id}/recipes", response_model=list[RecipeSummary])
def list_recipes(project_id: int, session: Session = Depends(get_session)) -> list[RecipeSummary]:
    _project_or_404(session, project_id)
    rows = session.exec(
        select(Recipe).where(Recipe.project_id == project_id).order_by(Recipe.created_at)
    ).all()
    return [_summary(r, MasterRecipe.model_validate_json(r.definition)) for r in rows]


@router.get("/api/projects/{project_id}/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe(project_id: int, recipe_id: int, session: Session = Depends(get_session)) -> RecipeDetail:
    row = _row_or_404(session, project_id, recipe_id)
    recipe = MasterRecipe.model_validate_json(row.definition)
    return RecipeDetail(**_summary(row, recipe).model_dump(), definition=recipe)


@router.put("/api/projects/{project_id}/recipes/{recipe_id}", response_model=RecipeSummary,
            responses={422: {"description": "the recipe references an unknown PEA/service/procedure/state"}})
def update_recipe(
    project_id: int, recipe_id: int, body: MasterRecipe, session: Session = Depends(get_session)
) -> RecipeSummary:
    row = _row_or_404(session, project_id, recipe_id)
    _validate_against_project(body, _project_peas(session, project_id))
    row.name = body.header.name
    row.version = body.header.version
    row.definition = body.model_dump_json()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _summary(row, body)


@router.delete("/api/projects/{project_id}/recipes/{recipe_id}", status_code=204)
def delete_recipe(project_id: int, recipe_id: int, session: Session = Depends(get_session)) -> None:
    session.delete(_row_or_404(session, project_id, recipe_id))
    session.commit()
