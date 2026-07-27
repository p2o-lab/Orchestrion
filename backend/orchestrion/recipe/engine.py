"""The recipe execution engine (M5.1 — the sequential/linear walking skeleton).

Executes a `MasterRecipe` by driving each step's PEA service procedure through the existing
control layer and advancing when a transition's `Condition` holds against live state.

The loop tracks a set of *active* steps. A transition fires when its condition is met **and**
every one of its `from_ids` is active; firing marks the from-steps done and starts the
to-steps (`END` targets simply finish that branch). This structure already generalises to
parallel splits (several `to_ids`) and joins (several `from_ids`) — M5.3 will exercise those;
M5.1 tests only the linear case with `StateReached`.

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

from orchestrion.recipe.conditions import StateOf, is_met
from orchestrion.recipe.model import END, MasterRecipe, RecipeStep

# Start a step on its PEA (the production impl calls control.start_service).
DriveStep = Callable[[RecipeStep], Awaitable[None]]
# A recipe-level event message sink (the production impl records EventKind.RECIPE).
OnEvent = Callable[[str], None]


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
        on_event: OnEvent | None = None,
        tick: float = 0.1,
        timeout: float = 60.0,
    ) -> None:
        self._recipe = recipe
        self._drive = drive_step
        self._state_of = state_of
        self._emit: OnEvent = on_event or (lambda _msg: None)
        self._tick = tick
        self._timeout = timeout
        self._aborted = False
        self._steps = {s.id: s for s in recipe.steps}

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
            for t in self._recipe.transitions:
                if all(f in run.active for f in t.from_ids) and is_met(t.condition, self._state_of):
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
        self._emit(f"step {step_id} started: {step.service} / procedure {step.procedure_id} on PEA {step.pea_id}")
        await self._drive(step)
