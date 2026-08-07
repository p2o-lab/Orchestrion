"""Live recipe runs — the in-memory registry of what is currently executing.

A run is a **control recipe** in ISA-88 terms ([IEC 61512-1] §6.2): the master recipe bound
to the actually-connected PEAs for one execution. `POL_Recipe_Engine_Design.md` §5 defers
persisting run history, so this mirrors the event log — in memory, for the app's lifetime.

Each run owns an `asyncio.Task` driving a `RecipeEngine`. The task lives in the same event
loop as the OPC UA client sessions and the API, which is the whole reason the backend is
async (`POL_MVP_and_Architecture.md` §1): subscription -> engine -> HTTP with no bridges.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from orchestrion.recipe.engine import RecipeEngine, RecipeRun, StepDriver
from orchestrion.recipe.model import MasterRecipe

MAX_EVENTS_PER_RUN = 500
"""Bounded like the PEA event log. A run is not an audit trail — that is M5.7."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunRecord:
    """One execution: its engine, its task, and what has happened so far."""

    run_id: int
    project_id: int
    recipe_id: int
    recipe_name: str
    run: RecipeRun
    engine: RecipeEngine
    started_at: datetime
    task: asyncio.Task | None = None
    finished_at: datetime | None = None
    events: list[dict] = field(default_factory=list)

    @property
    def is_live(self) -> bool:
        return self.task is not None and not self.task.done()

    def record(self, message: str) -> None:
        if len(self.events) >= MAX_EVENTS_PER_RUN:
            self.events.pop(0)
        self.events.append({"timestamp": _utcnow().isoformat(), "message": message})

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "status": self.run.status,
            "error": self.run.error,
            "steps": {sid: state.value for sid, state in self.run.steps.items()},
            "terminal": {sid: st.name for sid, st in self.run.terminal.items()},
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "events": self.events,
        }


class RunManager:
    """Every run this process has started, live or finished."""

    def __init__(self) -> None:
        self._runs: dict[int, RunRecord] = {}
        self._next_id = 1

    def live_for_recipe(self, recipe_id: int) -> RunRecord | None:
        """The recipe's current execution, if any.

        **One live run per recipe** — a deliberate narrowing. ISA-88 §8.6.3's equipment
        allocation is not modelled (`POL_Step_Model_ISA88.md` §12 item 3), so nothing stops
        two runs racing for the same service; pre-flight would catch it late and loudly
        (*"Stirring on PEA_A is EXECUTE (in use)"*) rather than never. Refusing the obvious
        case here is cheap and honest; real allocation is a later increment.
        """
        for record in self._runs.values():
            if record.recipe_id == recipe_id and record.is_live:
                return record
        return None

    def get(self, run_id: int) -> RunRecord | None:
        return self._runs.get(run_id)

    def all(self) -> list[RunRecord]:
        """Every run this process has started, live or finished."""
        return list(self._runs.values())

    def start(
        self,
        *,
        project_id: int,
        recipe_id: int,
        recipe: MasterRecipe,
        driver: StepDriver,
        state_of,
        value_of,
        tick: float = 0.1,
        timeout: float | None = None,
    ) -> RunRecord:
        """Build the engine, launch its task, and return the record immediately.

        The endpoint must not await the run: a batch can last hours (step model §11).
        """
        run_id = self._next_id
        self._next_id += 1

        record = RunRecord(
            run_id=run_id,
            project_id=project_id,
            recipe_id=recipe_id,
            recipe_name=recipe.header.name,
            run=RecipeRun(),
            engine=None,  # type: ignore[arg-type]  # set below; the engine needs `record`
            started_at=_utcnow(),
        )
        record.engine = RecipeEngine(
            recipe,
            driver=driver,
            state_of=state_of,
            value_of=value_of,
            on_event=record.record,
            tick=tick,
            timeout=timeout,
        )
        self._runs[run_id] = record
        record.task = asyncio.create_task(self._drive(record))
        return record

    async def _drive(self, record: RunRecord) -> None:
        """Run the engine and adopt its result as the record's own.

        `RecipeEngine.run()` builds its own `RecipeRun` and returns it at the end, so the
        record's placeholder must be replaced — otherwise `GET` would report a run stuck at
        `running` for ever. The engine already converts any failure into a failed run
        (unit 6), so an exception here means the engine itself broke.
        """
        try:
            record.run = await record.engine.run()
        except asyncio.CancelledError:
            record.run.status = "aborted"
            record.record("run task cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - never let a run task die silently
            record.run.status = "failed"
            record.run.error = f"engine crashed: {type(exc).__name__}: {exc}"
            record.record(record.run.error)
        finally:
            record.finished_at = _utcnow()

    def abort(self, run_id: int) -> RunRecord | None:
        """Ask a live run to stop after its current tick.

        ⚠ Commands **no PEA** — run-level propagation is deferred (step model §10), so
        anything mid-execution keeps running and the run's `error` names it.
        """
        record = self._runs.get(run_id)
        if record is not None and record.is_live:
            record.engine.abort()
        return record

    async def shutdown(self) -> None:
        """Cancel every live run — called from the app's lifespan."""
        for record in self._runs.values():
            if record.is_live and record.task is not None:
                record.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await record.task
