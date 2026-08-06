"""The recipe execution engine.

Executes a `MasterRecipe` by driving each step's PEA service procedure and advancing the
chart. The semantics are defined by `docs/POL_Step_Model_ISA88.md`; this module implements
them. Read that document before changing anything here.

**A step is `initiate + await termination`** ([IEC 61512-1] item 1982: *"each step defined
within a procedural element consists of initiating and awaiting termination of one
subordinate procedure"*). It is not "start it and watch for a condition".

**Advancing is two independent gates** (item 1341: *"Steps are initiated only after the
immediate predecessor(s) in series with them **have completed** **and** any intervening
transition conditions are true"*):

    gate 1  every from-step reached a Final State   — structural; nobody authors it
    gate 2  the transition's receptivity is true    — the author writes this

Gate 1 reads a **latched** record, never live state: the final state is recorded at the
instant it is observed, because `RESET` afterwards erases the evidence (step model §5).

Four step states, not two (step model §8): `RUNNING` -> [`COMPLETING`] -> `TERMINATED` ->
`DONE`. A *terminated* step has finished but its transition has not fired yet — which is
what makes "S1 finished, waiting for Temp > 80" observable.

**Scope of this unit.** Continuous procedures (which need an explicit `COMPLETE` before they
terminate — step model §2) are **not** handled here; a continuous step will never leave an
acting state and the run will time out. That is unit 4. Likewise `Always` (unit 5), the
held/paused *reporting* and the disconnect check (unit 6), and deliberate OR-branch
grouping (unit 8) are deferred, each noted at its site below.

Decoupled for testability: `drive_step`, `reset_step`, `state_of` and `value_of` are
injected callbacks. **No OPC UA code here** — the engine adds orchestration logic only.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from orchestrion.recipe.conditions import EvalContext, StateOf, ValueOf, is_met
from orchestrion.recipe.model import END, MasterRecipe, RecipeStep
from orchestrion.state.classification import StateClass, classify, is_final
from orchestrion.state.codes import ServiceState

# Start a step on its PEA. The production impl runs pre-flight (`control.ensure_idle`),
# `control.start_service`, then `control.await_started`.
DriveStep = Callable[[RecipeStep], Awaitable[None]]
# Return a finished step's service to IDLE. [IEC 61512-1] Table B.2 makes this mandatory:
# RESETTING "always becomes active between executions of the Process-oriented task".
ResetStep = Callable[[RecipeStep], Awaitable[None]]
# A recipe-level event message sink (the production impl records EventKind.RECIPE).
OnEvent = Callable[[str], None]


# A live value lookup for ValueThreshold conditions; defaults to "no values" if not supplied.
def _no_values(_pea_id: int, _value_name: str) -> float | None:
    return None


class StepState(str, Enum):
    """Where one step is in its lifecycle — `POL_Step_Model_ISA88.md` §8."""

    RUNNING = "running"
    """The service is in an acting state. Keep waiting."""

    COMPLETING = "completing"
    """*Continuous procedures only* — the receptivity fired, `COMPLETE` was sent, and we
    are awaiting the final state. **Set by unit 4; never set by this unit.**"""

    TERMINATED = "terminated"
    """A Final State was reached and latched. Gate 1 is satisfied; the step is waiting for
    its transition's receptivity (gate 2)."""

    DONE = "done"
    """The transition fired. The step is settled and its service has been `RESET`."""


@dataclass
class RecipeRun:
    """The live/finished state of one recipe execution."""

    status: str = "running"  # running | completed | aborted | failed
    steps: dict[str, StepState] = field(default_factory=dict)
    """Every step that has been activated, and where it is. Steps not yet reached are absent."""
    terminal: dict[str, ServiceState] = field(default_factory=dict)
    """**The latch** (step model §5) — which Final State each terminated step reached,
    recorded at the instant it was observed. Gate 1 reads this, never live state."""
    error: str | None = None

    @property
    def done(self) -> set[str]:
        """Steps whose transition has fired."""
        return {sid for sid, st in self.steps.items() if st is StepState.DONE}

    @property
    def unfinished(self) -> set[str]:
        """Activated steps that have not yet settled — the run continues while any exist."""
        return {sid for sid, st in self.steps.items() if st is not StepState.DONE}


class RecipeEngine:
    """Executes one `MasterRecipe`. Instantiate, `await run()`, or `abort()` mid-run."""

    def __init__(
        self,
        recipe: MasterRecipe,
        *,
        drive_step: DriveStep,
        reset_step: ResetStep,
        state_of: StateOf,
        value_of: ValueOf | None = None,
        on_event: OnEvent | None = None,
        tick: float = 0.1,
        timeout: float = 60.0,
    ) -> None:
        self._recipe = recipe
        self._drive = drive_step
        self._reset = reset_step
        self._state_of = state_of
        self._value_of = value_of or _no_values
        self._emit: OnEvent = on_event or (lambda _msg: None)
        self._tick = tick
        # TODO(unit 6): default becomes None — a real batch runs for hours, and this is what
        # turns a deliberately HELD batch into a false "failed" (step model §11).
        self._timeout = timeout
        self._aborted = False
        self._steps = {s.id: s for s in recipe.steps}
        self._terminated_at: dict[str, float] = {}
        """step id -> monotonic time it was latched. `Elapsed` counts from here, because a
        transition becomes *enabled* when its last from-step terminates (step model §9)."""

    def abort(self) -> None:
        """Request the run stop after the current tick (idempotent).

        TODO(unit 6): this commands no PEA, so an aborted run leaves services executing.
        """
        self._aborted = True

    async def run(self) -> RecipeRun:
        run = RecipeRun()
        self._emit(f"recipe {self._recipe.header.name!r} started")

        # Start steps = those that are never a transition target. Valid because cycles are
        # rejected (chart §2/§10) — with a cycle this yields zero start steps.
        # TODO(unit 5): guard zero / several start steps here as well as in the builder.
        targets = {d for t in self._recipe.transitions for d in t.to_ids}
        for step in self._recipe.steps:
            if step.id not in targets:
                await self._activate(step.id, run)

        deadline = time.monotonic() + self._timeout
        while run.unfinished and not self._aborted:
            if time.monotonic() > deadline:
                run.status, run.error = "failed", "timed out"
                self._emit("recipe timed out")
                return run

            # Observe first, then fire: gate 1 must be settled from this pass's readings
            # before any receptivity is evaluated against them.
            self._observe(run)
            if run.status == "failed":
                return run

            if not await self._fire(run):
                await asyncio.sleep(self._tick)  # nothing advanced — wait for the plant

        if self._aborted:
            run.status = "aborted"
            self._emit("recipe aborted")
        elif not run.unfinished:
            run.status = "completed"
            self._emit(f"recipe {self._recipe.header.name!r} completed")
        return run

    # ── the two gates ───────────────────────────────────────────────────────────────

    def _observe(self, run: RecipeRun) -> None:
        """Latch any running step that has reached a Final State — **gate 1**.

        Synchronous: `state_of` is a plain lookup against the registry snapshot, no I/O.
        """
        for step_id in [s for s, st in run.steps.items() if st is StepState.RUNNING]:
            step = self._steps[step_id]
            name = self._state_of(step.pea_id, step.service)
            if name is None:
                # No reading: the PEA is disconnected, or the service is unknown.
                # TODO(unit 6): a disconnect must fail the run — we have lost observability
                # of a running procedural element (step model §11). Today we keep waiting.
                continue

            state = ServiceState[name]
            if not is_final(state):
                # Acting -> the PEA is working. HELD/PAUSED -> a recoverable exception that
                # needs an *operator* command; [IEC 61512-1] items 2341-2352 say the run
                # waits, so waiting is correct here.
                # TODO(unit 6): report held/paused as run status rather than silently waiting.
                continue

            # §5 — record WHICH final state, at the instant of observation. `RESET` later
            # drives COMPLETED -> RESETTING -> IDLE and erases the evidence; gate 1 must
            # never re-derive completion from a state that has since moved on.
            run.terminal[step_id] = state
            self._terminated_at[step_id] = time.monotonic()
            run.steps[step_id] = StepState.TERMINATED
            self._emit(f"step {step_id} terminated: {state.name}")

            if classify(state) is StateClass.TERMINAL_ABNORMAL:
                # STOP/ABORT are the non-recoverable exception levels ([61512-1] items
                # 2355-2369). Item 3450 says the parent "may" progress — deliberately open,
                # so this is our choice (step model §7): the run fails, no further steps start.
                # TODO(unit 6): also name every sibling step still executing.
                run.status = "failed"
                run.error = f"step {step_id!r} terminated abnormally: {state.name}"
                self._emit(f"recipe failed: {run.error}")
                return

    async def _fire(self, run: RecipeRun) -> bool:
        """Fire every transition whose both gates hold. Returns whether anything fired."""
        fired = False
        # Captured once, and safe: `_terminated_at` is only written by `_observe`, which has
        # already finished for this pass. (The previous implementation captured `now` here
        # and wrote activation times inside the same loop, which could make elapsed negative.)
        now = time.monotonic()

        # TODO(unit 8): group a step's outgoing transitions and fire at most one, in explicit
        # priority order (chart §8). Today mutual exclusion is incidental — a fired from-step
        # becomes DONE, so a later transition's gate 1 fails.
        for transition in self._recipe.transitions:
            # gate 1 — structural. Reads the latch, never live state.
            if not all(
                run.steps.get(f) is StepState.TERMINATED for f in transition.from_ids
            ):
                continue

            # §9 — a transition becomes *enabled* when its last from-step terminated, so
            # `Elapsed(30)` on a self-completing step means "wait 30 s after it finishes".
            elapsed = now - max(self._terminated_at[f] for f in transition.from_ids)
            context = EvalContext(self._state_of, self._value_of, elapsed)

            # gate 2 — the author's receptivity.
            if not is_met(transition.condition, context):
                continue

            for from_id in transition.from_ids:
                # §5 / §12 item 0a — RESET on advance, not on termination. Until now the
                # service sat in its final state, which is what makes a terminated-but-not-
                # advanced step visible on the PEA.
                await self._reset(self._steps[from_id])
                run.steps[from_id] = StepState.DONE

            # Emitted here, between deactivating the predecessors and activating the
            # successors, because that is the causal order: the transition clears, and
            # *therefore* the next steps start. Emitting it after activation made the
            # operator timeline read backwards ("s2 started" before "transition fired").
            self._emit(
                f"transition fired: {sorted(transition.from_ids)} -> "
                f"{sorted(transition.to_ids)}"
            )

            for to_id in transition.to_ids:
                if to_id != END:
                    await self._activate(to_id, run)

            fired = True
        return fired

    async def _activate(self, step_id: str, run: RecipeRun) -> None:
        step = self._steps[step_id]
        run.steps[step_id] = StepState.RUNNING
        self._emit(
            f"step {step_id} started: {step.service} / procedure {step.procedure_id} "
            f"on PEA {step.pea_id}"
        )
        await self._drive(step)
