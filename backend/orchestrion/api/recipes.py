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
from orchestrion.api.live import registry
from orchestrion.mtp.model import ServiceProcedure
from orchestrion.recipe.driver import PlantStepDriver
from orchestrion.recipe.model import (
    END, Always, And, Condition, Elapsed, MasterRecipe, Or, RecipeStep, StateReached,
    ValueThreshold,
)
from orchestrion.recipe.runs import RunManager, RunRecord
from orchestrion.state.codes import ServiceState

router = APIRouter(tags=["recipes"])

# One run manager for the app's lifetime, like `live.registry`. main.lifespan cancels any
# live run on exit. Runs are in-memory only — persisting history is a later increment
# (`POL_Recipe_Engine_Design.md` §9).
runs = RunManager()


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

    The engine guards this too, but a recipe can be `POST`ed straight past the
    builder, so the API is where a malformed one has to be stopped — the builder is an
    authoring aid, not a safety boundary (`POL_Recipe_Chart_GRAFCET.md` §2).

    An **empty** recipe is exempt (2026-09-05). `ProjectView.createRecipe` posts
    `steps: []` / `transitions: []` and then opens the canvas on the stored row, so
    gating creation on this check made a new recipe impossible: zero steps yields zero
    initial steps, which is not one, so the endpoint answered 422 before the author could
    draw anything. The message compounded it, reporting "every step is a transition
    target (a cycle?)" when there were no steps and no cycle. A recipe with no shape yet
    has no shape to check, and nothing unrunnable can start regardless: the run path
    guards the initial step independently.
    """
    if not recipe.steps:
        return
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


def _contains_always(condition: Condition) -> bool:
    """Does `Always` appear anywhere in this condition tree?

    Added 2026-09-05, replacing an `isinstance(condition, Always)` test that read only the
    OUTERMOST node. That test passed a nested `Always` straight through, and
    `Or[Always, ...]` is exactly as fatal as a bare `Always`: an `Or` is true the moment any
    child is, so a continuous service would be started and completed in the same instant.
    Only a bare `Always` was ever refused, and the frontend's `containsAlways` had walked the
    tree all along — the two sides disagreed, and the server was the lax one, which
    is the side that matters because a recipe can be POSTed without the builder ever opening.
    This mirrors the frontend exactly, so the two now refuse the same charts.
    """
    if isinstance(condition, Always):
        return True
    if isinstance(condition, (And, Or)):
        return any(_contains_always(sub) for sub in condition.conditions)
    return False


def _check_continuous_steps_have_a_real_receptivity(
    recipe: MasterRecipe, peas: dict[int, PeaModel]
) -> None:
    """`Always` is invalid on a transition with a *continuous* step in its `from_ids`.

    For a continuous procedure the receptivity **is** the completion criterion
    (`POL_Step_Model_ISA88.md` §2), so `Always` would start the service and complete it in
    the same instant. Stated over the whole `from_ids` rather than one step's exit, because
    a continuous step may also feed an AND-join (chart §4, §5(b)), and over the whole
    condition tree rather than its outermost node (see `_contains_always`).
    """
    steps = {s.id: s for s in recipe.steps}
    for transition in recipe.transitions:
        if not _contains_always(transition.condition):
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
    _refuse_while_running(recipe_id, "edited")
    _validate_against_project(body, _project_peas(session, project_id))
    row.name = body.header.name
    row.version = body.header.version
    row.definition = body.model_dump_json()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _summary(row, body)


def _refuse_while_running(recipe_id: int, verb: str) -> None:
    """A recipe with a live run must not be edited or deleted.

    The run holds its own parsed `MasterRecipe`, so it would keep executing the old
    definition against a row that has changed or vanished — the stored recipe and what the
    plant is actually doing would silently disagree, which is the last thing an operator
    reading a run should have to suspect.
    """
    live = runs.live_for_recipe(recipe_id)
    if live is not None:
        raise HTTPException(
            409,
            f"recipe {recipe_id} is running (run {live.run_id}) and cannot be {verb}; "
            "abort the run first",
        )


@router.delete("/api/projects/{project_id}/recipes/{recipe_id}", status_code=204,
               responses={409: {"description": "the recipe is currently running"}})
def delete_recipe(project_id: int, recipe_id: int, session: Session = Depends(get_session)) -> None:
    row = _row_or_404(session, project_id, recipe_id)
    _refuse_while_running(recipe_id, "deleted")
    session.delete(row)
    session.commit()


# ── running a recipe ────────────────────────────────────────────────────────────────
#
# Until now `RecipeEngine` had no production caller at all — it existed only for tests.
# This is the seam that makes it reachable.


def _run_or_404(run_id: int, project_id: int) -> RunRecord:
    record = runs.get(run_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(404, f"run {run_id} not found in project {project_id}")
    return record


@router.post("/api/projects/{project_id}/recipes/{recipe_id}/run", status_code=201,
             responses={409: {"description": "already running, or a PEA is not connected"},
                        422: {"description": "the recipe cannot run on this project"}})
async def start_run(
    project_id: int, recipe_id: int, session: Session = Depends(get_session)
) -> dict:
    """Bind a master recipe to the project's connected PEAs and start executing it.

    Returns as soon as the run is launched — a batch can last hours (step model §11), so
    the endpoint never awaits it. Poll `GET …/runs/{run_id}` for progress.

    **`async def` is load-bearing**, not style: launching the run is `asyncio.create_task`,
    which needs a *running* loop. FastAPI executes a sync endpoint in a threadpool, where
    there is none — the task would never start and the coroutine would be garbage-collected
    un-awaited. Same shape as `api/control.py`'s handlers, which drive OPC UA directly.
    """
    row = _row_or_404(session, project_id, recipe_id)
    recipe = MasterRecipe.model_validate_json(row.definition)

    if (live := runs.live_for_recipe(recipe_id)) is not None:
        raise HTTPException(409, f"recipe {recipe_id} is already running (run {live.run_id})")

    # Re-validate at run time, not only at save: the project's PEAs can have changed since,
    # and starting a recipe that cannot run is worse than refusing it.
    peas = _project_peas(session, project_id)
    _validate_against_project(recipe, peas)

    # Every PEA the recipe touches must be connected *before* the first step runs. The
    # driver would otherwise raise mid-run and fail it — correct, but late and confusing.
    missing = sorted({s.pea_id for s in recipe.steps if not registry.is_connected(s.pea_id)})
    if missing:
        raise HTTPException(409, f"connect these PEAs before running: {missing}")

    driver = PlantStepDriver(registry, peas)
    record = runs.start(
        project_id=project_id,
        recipe_id=recipe_id,
        recipe=recipe,
        driver=driver,
        state_of=driver.state_of,
        value_of=driver.value_of,
    )
    return {"run_id": record.run_id, "status": record.run.status}


@router.get("/api/projects/{project_id}/runs/{run_id}")
def get_run(project_id: int, run_id: int) -> dict:
    """A run's live status, per-step states, latched final states, and event trail."""
    return _run_or_404(run_id, project_id).to_dict()


@router.get("/api/projects/{project_id}/runs")
def list_runs(project_id: int) -> list[dict]:
    """Every run this process has started for the project, newest first."""
    return [
        r.to_dict() for r in sorted(
            (r for r in runs.all() if r.project_id == project_id),
            key=lambda r: r.run_id, reverse=True,
        )
    ]


@router.post("/api/projects/{project_id}/runs/{run_id}/abort")
def abort_run(project_id: int, run_id: int) -> dict:
    """Ask a live run to stop after its current tick.

    Commands **no PEA** — run-level propagation down to active steps is deferred
    (step model §10: [IEC 61512-1] items 2233-2235 say the standard *"does not specify
    propagation rules"*). Anything mid-execution keeps running, and the run's `error`
    names it so the operator is told rather than left to find out.
    """
    record = _run_or_404(run_id, project_id)
    runs.abort(run_id)
    return {"run_id": record.run_id, "status": record.run.status}
