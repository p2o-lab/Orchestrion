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
from orchestrion.mtp.model import ServiceProcedure
from orchestrion.recipe.model import (
    END, Always, And, Condition, Elapsed, MasterRecipe, Or, RecipeStep, StateReached,
    ValueThreshold,
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
        # Nothing to *resolve*: neither references the plant. `Always` would otherwise fall
        # through this chain unnamed, which reads as an oversight rather than a decision.
        # Its one restriction — not on a continuous step's transition — is checked in
        # `_check_continuous_steps_have_a_real_receptivity`, because it needs the transition
        # it sits on, not just the condition.
        pass
    elif isinstance(cond, (And, Or)):
        for sub in cond.conditions:
            _check_condition(sub, peas, where)


def _procedure(peas: dict[int, PeaModel], step: RecipeStep) -> ServiceProcedure:
    """The parsed procedure a step binds to. Assumes the reference checks below passed."""
    pea = peas[step.pea_id]
    service = next(s for s in pea.services if s.name == step.service)
    return next(p for p in service.procedures if p.procedure_id == step.procedure_id)


def _check_exactly_one_initial_step(recipe: MasterRecipe) -> None:
    """[IEC 61512-1] item 1337 — a procedure has *"a defined beginning and end"*. Singular.

    The engine guards this too (unit 5), but a recipe can be `POST`ed straight past the
    builder, so the API is where a malformed one has to be stopped — the builder is an
    authoring aid, not a safety boundary (`POL_Recipe_Chart_GRAFCET.md` §2).
    """
    targets = {d for t in recipe.transitions for d in t.to_ids}
    initial = sorted(s.id for s in recipe.steps if s.id not in targets)
    if len(initial) == 1:
        return
    detail = (
        "found none — every step is a transition target (a cycle?)"
        if not initial
        else f"found {len(initial)}: {initial}"
    )
    raise HTTPException(
        422,
        "a recipe needs exactly one initial step "
        f"([IEC 61512-1] item 1337, 'a defined beginning and end'); {detail}",
    )


def _check_no_cycles(recipe: MasterRecipe) -> None:
    """Reject a chart that loops back — `POL_Recipe_Chart_GRAFCET.md` §2/§10.

    ISA-88's procedure model is *"steps **in series, in parallel, or a combination of
    both**"* (item 1339) with a defined beginning and end; it never describes a loop, and
    its only mention of "looping back" (item 3112) is a batch manager's **recipe-editing**
    capability. GRAFCET does permit cycles (§6.2.2), but per chart §0a GRAFCET is a borrowed
    notation, not our conformance target — so **this is consistent with ISA-88, and allowing
    cycles would be unsupported by it.**

    It is also what makes the initial step inferable from topology at all: in a cyclic chart
    every step is a transition target, so `_check_exactly_one_initial_step` finds none and
    the engine would have nothing to activate.

    Kahn's algorithm — peel off steps with no remaining predecessor; whatever survives is a
    cycle, and naming those steps is what makes the error actionable.
    """
    successors: dict[str, set[str]] = {s.id: set() for s in recipe.steps}
    incoming: dict[str, int] = {s.id: 0 for s in recipe.steps}
    for transition in recipe.transitions:
        for source in transition.from_ids:
            for target in transition.to_ids:
                if target == END or target in successors[source]:
                    continue  # END is not a step; parallel edges count once
                successors[source].add(target)
                incoming[target] += 1

    queue = [sid for sid, n in incoming.items() if n == 0]
    settled = 0
    while queue:
        sid = queue.pop()
        settled += 1
        for target in successors[sid]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)

    if settled != len(recipe.steps):
        looped = sorted(sid for sid, n in incoming.items() if n > 0)
        raise HTTPException(
            422,
            f"the recipe loops back on itself: {looped}. ISA-88 procedures run from a "
            "defined beginning to a defined end (item 1337); repeating steps is not modelled.",
        )


def _check_continuous_steps_have_a_real_receptivity(
    recipe: MasterRecipe, peas: dict[int, PeaModel]
) -> None:
    """`Always` is invalid on a transition with a *continuous* step in its `from_ids`.

    For a continuous procedure the receptivity **is** the completion criterion
    (`POL_Step_Model_ISA88.md` §2), so `Always` would start the service and complete it in
    the same instant. Stated over the whole `from_ids` rather than one step's exit, because
    a continuous step may also feed an AND-join (chart §4, §5(b)).
    """
    steps = {s.id: s for s in recipe.steps}
    for transition in recipe.transitions:
        if not isinstance(transition.condition, Always):
            continue
        for source in transition.from_ids:
            if _procedure(peas, steps[source]).is_self_completing:
                continue
            raise HTTPException(
                422,
                f"transition {transition.from_ids}->{transition.to_ids}: step {source!r} runs a "
                "continuous procedure, whose receptivity IS its completion criterion — "
                "'Always' would complete it the instant it starts. Give it a real condition "
                "(a duration, a threshold, an operator confirmation).",
            )


def _validate_against_project(recipe: MasterRecipe, peas: dict[int, PeaModel]) -> None:
    """Reject a recipe that could not run on this project (HTTP 422).

    Two layers, in order: every reference must **resolve** against the project's actual
    PEAs, and then the graph must have a **runnable shape**. The pure model only checks
    internal consistency (ids unique, endpoints resolve) — deliberately, so that whatever is
    already stored still loads; this is the gate for anything created or updated.
    """
    for step in recipe.steps:
        where = f"step {step.id!r}"
        pea = _require_service(peas, step.pea_id, step.service, where)
        service = next(s for s in pea.services if s.name == step.service)
        if not any(p.procedure_id == step.procedure_id for p in service.procedures):
            raise HTTPException(422, f"{where}: procedure {step.procedure_id} not on service {step.service!r}")

    for t in recipe.transitions:
        _check_condition(t.condition, peas, f"transition {t.from_ids}->{t.to_ids}")

    # Shape. These run after the reference checks because they lean on them: `_procedure`
    # assumes every step resolves.
    _check_exactly_one_initial_step(recipe)
    _check_no_cycles(recipe)
    _check_continuous_steps_have_a_real_receptivity(recipe, peas)


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
