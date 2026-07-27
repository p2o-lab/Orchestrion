"""The recipe execution engine (M5.1 — the sequential/linear walking skeleton).

Executes a `MasterRecipe` by driving each step's PEA service procedure through the existing
control layer and advancing when a transition's `Condition` holds against live state.

The loop tracks a set of *active* steps. A transition fires when its condition is met **and**
every one of its `from_ids` is active; firing marks the from-steps done and starts the
to-steps (`END` targets simply finish that branch). From this single rule fall all four SFC
branch forms:

* **AND-divergence (parallel split)** — one transition with several `to_ids`: all start together.
* **AND-convergence (join)** — one transition with several `from_ids`: fires only once **all**
  those branches are active (typically with an `And` condition over them).
* **OR-divergence (selection)** — several transitions leaving the *same* step: the first whose
  condition holds **consumes** the step (firing removes it from `active`), so the alternatives
  are mutually exclusive. Ties (two conditions true in one tick) break by **transition order**
  — the earlier-listed transition wins (priority), the SFC-standard resolution.
* **OR-convergence (selection merge)** — several transitions (one per alternative branch) sharing
  a `to` step: since only one branch was ever active, only its transition fires. No special gate.

M5.3 exercised the AND forms; M5.6 (pulled forward) the OR forms.

Decoupled for testability: the engine is handed `drive_step` (start a step on its PEA) and
`state_of` (read live state) as callbacks. Production wires them to `opcua.control` + the
`PeaRegistry` (see `factory.py`, a later unit); unit tests pass fakes. **No OPC UA code here** —
the engine adds orchestration logic only.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from orchestrion.recipe.conditions import EvalContext, StateOf, ValueOf, is_met
from orchestrion.recipe.model import END, MasterRecipe, RecipeStep

# Start a step on its PEA (the production impl calls control.start_service).
DriveStep = Callable[[RecipeStep], Awaitable[None]]
# A recipe-level event message sink (the production impl records EventKind.RECIPE).
OnEvent = Callable[[str], None]

# A live value lookup for ValueThreshold conditions; defaults to "no values" if not supplied.
def _no_values(_pea_id: int, _value_name: str) -> float | None:
    return None


@dataclass
class RecipeRun:
    """The live/finished state of one recipe execution."""

    status: str = "running"  # running | completed | aborted | failed
    active: set[str] = field(default_factory=set)  # step ids currently executing
    done: set[str] = field(default_factory=set)  # step ids finished
    error: str | None = None


class RecipeEngine:
    """Executes one `MasterRecipe`. Instantiate, `await run()`, or `abort()` mid-run."""

    def __init__(
        self,
        recipe: MasterRecipe,
        *,
        drive_step: DriveStep,
        state_of: StateOf,
        value_of: ValueOf | None = None,
        on_event: OnEvent | None = None,
        tick: float = 0.1,
        timeout: float = 60.0,
    ) -> None:
        self._recipe = recipe
        self._drive = drive_step
        self._state_of = state_of
        self._value_of = value_of or _no_values
        self._emit: OnEvent = on_event or (lambda _msg: None)
        self._tick = tick
        self._timeout = timeout
        self._aborted = False
        self._steps = {s.id: s for s in recipe.steps}
        self._active_since: dict[str, float] = {}  # step id -> monotonic activation time

    def abort(self) -> None:
        """Request the run stop after the current tick (idempotent)."""
        self._aborted = True

    async def run(self) -> RecipeRun:
        run = RecipeRun()
        self._emit(f"recipe {self._recipe.header.name!r} started")

        # Start steps = those that are never a transition target (no incoming edge).
        targets = {d for t in self._recipe.transitions for d in t.to_ids}
        for step in self._recipe.steps:
            if step.id not in targets:
                await self._activate(step.id, run)

        deadline = time.monotonic() + self._timeout
        while run.active and not self._aborted:
            if time.monotonic() > deadline:
                run.status, run.error = "failed", "timed out"
                self._emit("recipe timed out")
                return run
            fired = False
            now = time.monotonic()
            for t in self._recipe.transitions:
                if not all(f in run.active for f in t.from_ids):
                    continue
                # elapsed = time since the last of this transition's from-steps started.
                elapsed = now - max(self._active_since[f] for f in t.from_ids)
                ctx = EvalContext(self._state_of, self._value_of, elapsed)
                if is_met(t.condition, ctx):
                    for f in t.from_ids:  # the from-steps have completed their part
                        run.active.discard(f)
                        run.done.add(f)
                    for d in t.to_ids:
                        if d != END:
                            await self._activate(d, run)
                    fired = True
            if not fired:  # nothing advanced this pass — wait for the plant to move
                await asyncio.sleep(self._tick)

        if self._aborted:
            run.status = "aborted"
            self._emit("recipe aborted")
        elif not run.active:
            run.status = "completed"
            self._emit(f"recipe {self._recipe.header.name!r} completed")
        return run

    async def _activate(self, step_id: str, run: RecipeRun) -> None:
        step = self._steps[step_id]
        run.active.add(step_id)
        self._active_since[step_id] = time.monotonic()
        self._emit(f"step {step_id} started: {step.service} / procedure {step.procedure_id} on PEA {step.pea_id}")
        await self._drive(step)
