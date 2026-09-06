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

**Two kinds of procedure, two shapes of step** (step model §2, `[2658-4:2022]` §6.2.3.1/.2):

* **self-completing** — the PEA walks to `COMPLETED` on its own. The receptivity is an
  *additional* gate evaluated **after** termination.
* **continuous** — the service holds `EXECUTE` indefinitely and only an explicit `COMPLETE`
  ends it (*"the Complete command to terminate the service is sent to the PEA by the POL"*).
  Its receptivity **is** the completion criterion, evaluated **while it runs**.

So advancing over a continuous step is **two phases**: the receptivity fires and we send
`COMPLETE` (the transition is *armed*), then termination is latched and the transition
clears. An armed transition is never re-evaluated (chart §5(a)).

**Exceptions are graded, not lumped together** ([IEC 61512-1] §7.4, items 2341-2369). `PAUSE`
and `HOLD` are *recoverable* — the run reports `paused`/`held`, waits with no clock, and
resumes on its own when the operator does. `STOP` and `ABORT` are not — the run fails. A PEA
**disconnecting** also fails it: unlike HELD, the state is then *unknown* (§11).

**Still deferred:** deliberate OR-branch grouping, and run-level commands
propagating down to active steps (step model §10) — each noted at its site below.

Decoupled for testability: the engine is handed a `StepDriver` (act on / ask about a step's
service) plus `state_of` / `value_of` (read the live snapshot, for receptivities).
**No OPC UA code here** — the engine adds orchestration logic only; tests pass a fake.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from orchestrion.recipe.conditions import EvalContext, StateOf, ValueOf, is_met
from orchestrion.recipe.model import END, MasterRecipe, RecipeStep, Transition
from orchestrion.state.classification import StateClass, classify, is_final
from orchestrion.state.codes import ServiceState

class StepDriver(Protocol):
    """Everything the engine needs to **act on** or **ask about** one step's service.

    One injected collaborator rather than a fistful of callables. The engine still owns no
    OPC UA code — it holds no connection, no `Service`, no parsed `Pea` — but these four
    verbs and two questions are all facets of the same thing, and passing them separately
    made that harder to see, not easier. Production: `recipe/driver.py`; tests pass a fake.
    """

    async def start(self, step: RecipeStep) -> None:
        """Pre-flight, start, and wait until the service has left IDLE.

        Production: `control.ensure_idle` -> `control.start_service` -> `control.await_started`
        (step model §2/§4). Must return only once the step is genuinely under way.
        """

    async def complete(self, step: RecipeStep) -> None:
        """End a *continuous* step — [2658-4:2022] §6.2.3.2: *"the Complete command to
        terminate the service is sent to the PEA by the POL or the operator."*"""

    async def reset(self, step: RecipeStep) -> None:
        """Return a finished step's service to IDLE. [IEC 61512-1] Table B.2 makes this
        mandatory: RESETTING *"always becomes active between executions."*"""

    async def read_state(self, step: RecipeStep) -> "ServiceState | None":
        """This step's service state, **fresh enough to latch on** (step model §5).

        Deliberately **not** the same source as `state_of`. `state_of` reads the live
        snapshot — a subscription cache — which is right for evaluating a receptivity but
        **not** for deciding a step has terminated: on a *reused* service the cache can still
        hold the previous execution's `COMPLETED`, and the latch cannot be fresher than its
        source. Production does a direct read; how it answers is the driver's business.

        `None` means "no reading". Disconnection is `is_connected`, deliberately separate.
        """

    def is_self_completing(self, step: RecipeStep) -> bool:
        """[2658-4:2022] Table 36 #4b `IsSelfCompleting`, resolved from the PEA's MTP.

        Asked rather than stored on `RecipeStep`, deliberately: that is the *persisted* wire
        model, and the kind is a property of the **plant**, not of the recipe. Storing it
        would let a saved recipe go stale, and an MTP re-import silently invalidate it.
        """

    def is_connected(self, pea_id: int) -> bool:
        """Whether the POL still holds a live connection. Separate from a `None` state,
        which means *both* "disconnected" and "no such service" (step model §11)."""


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
    are awaiting the final state."""

    TERMINATED = "terminated"
    """A Final State was reached and latched. Gate 1 is satisfied; the step is waiting for
    its transition's receptivity (gate 2)."""

    DONE = "done"
    """The transition fired. The step is settled and its service has been `RESET`."""


@dataclass
class RecipeRun:
    """The live/finished state of one recipe execution."""

    status: str = "running"
    """`running` | `held` | `paused` | `completed` | `aborted` | `failed`.

    **Observed, not commanded** (step model §10): `held`/`paused` are derived each pass from
    the steps' live states and clear again on their own when the operator resumes. Only the
    three terminal values are set once and final."""
    steps: dict[str, StepState] = field(default_factory=dict)
    """Every step that has been activated, and where it is. Steps not yet reached are absent."""
    terminal: dict[str, ServiceState] = field(default_factory=dict)
    """**The latch** (step model §5) — which Final State each terminated step reached,
    recorded at the instant it was observed. Gate 1 reads this, never live state."""
    interrupted: dict[str, ServiceState] = field(default_factory=dict)
    """Which steps are currently `HELD` or `PAUSED` — step model §7 levels 1-2.

    Recomputed every pass and **cleared by itself** when the operator releases the service,
    exactly like `status`. It exists because `status` alone says a run is held without saying
    *where*: an interrupted step stays `RUNNING` in `steps` (HELD is neither acting nor
    final, so `_observe` falls through), so nothing downstream could tell a held step from a
    working one. Reported so an operator can see which module is waiting on them."""
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
        driver: StepDriver,
        state_of: StateOf,
        value_of: ValueOf | None = None,
        on_event: OnEvent | None = None,
        tick: float = 0.1,
        timeout: float | None = None,
    ) -> None:
        self._recipe = recipe
        self._driver = driver
        # `state_of` / `value_of` stay outside the driver on purpose: they feed
        # `conditions.is_met`, which is **pure and synchronous** so it stays trivially
        # testable. They read the live snapshot; the driver reads the plant. See
        # `StepDriver.read_state` for why that difference matters at the latch.
        self._state_of = state_of
        self._value_of = value_of or _no_values
        self._emit: OnEvent = on_event or (lambda _msg: None)
        self._tick = tick
        # §11 — **no global timeout by default.** Real batches run for hours, ISA-88 has no
        # such concept, and a clock on the whole run is exactly what turns a deliberately
        # HELD batch into a false `failed`. A run ends when the chart ends it, when it is
        # aborted, or when something actually goes wrong. Tests pass a short one explicitly.
        self._timeout = timeout
        self._aborted = False
        self._run = RecipeRun()
        """The one run object, created up front and mutated in place.

        **It must be reachable *before* `run()` returns**, or nothing can observe a run
        while it is running. `run()` used to build its own and hand it back at the end, so
        `RunManager` held a placeholder that stayed `status="running", steps={}` for the
        whole execution — making held/paused reporting and §8's four step states
        invisible from outside, and M5.5's live view impossible. Exposed via `state`.
        """
        self._steps = {s.id: s for s in recipe.steps}
        self._terminated_at: dict[str, float] = {}
        """step id -> monotonic time it was latched. For a **self-completing** step the
        transition becomes *enabled* when it terminates, so `Elapsed(30)` is a **dwell**:
        "wait 30 s after it finishes" (step model §9)."""
        self._running_since: dict[str, float] = {}
        """step id -> monotonic time it was activated. For a **continuous** step the
        transition is enabled *immediately* — the receptivity IS the completion criterion —
        so `Elapsed(30)` is a **duration**: "run for 30 s, then complete it" (§9)."""
        self._armed: set[int] = set()
        """Indices of transitions that have fired their receptivity and sent `COMPLETE`, and
        are now awaiting termination. **The winning branch is latched here** (chart §5(a)):
        an armed transition is never re-evaluated, so a receptivity falling false during
        `COMPLETING` cannot strand the run with no true branch."""

    @property
    def state(self) -> RecipeRun:
        """The live run — the same object `run()` mutates and returns.

        Read it at any time to see progress; it is not a copy.
        """
        return self._run

    def abort(self) -> None:
        """Request the run stop after the current tick (idempotent).

        **Commands no PEA.** Run-level `PAUSE`/`HOLD`/`STOP`/`ABORT` propagating down to
        active steps is deferred (step model §10) — [IEC 61512-1] items 2233-2235 say the
        standard *"does not specify propagation rules"*, so it is ours to design and it is
        not designed yet. Until then an aborted run leaves anything mid-execution running,
        and `run.error` names it so the operator is told rather than left to discover it.
        """
        self._aborted = True

    def _still_executing(self, run: RecipeRun, exclude: set[str] | None = None) -> list[str]:
        """Steps whose service is still working — the ones a failure or abort leaves behind."""
        skip = exclude or set()
        return sorted(
            sid
            for sid, st in run.steps.items()
            if sid not in skip and st in (StepState.RUNNING, StepState.COMPLETING)
        )

    def _with_siblings(
        self, message: str, run: RecipeRun, exclude: set[str] | None = None
    ) -> str:
        """Append what this failure leaves running — step model §7.

        A **known limitation, stated rather than hidden**: run-level propagation is a later
        increment, so a failed batch can leave equipment running. The operator must be told.
        """
        still = self._still_executing(run, exclude)
        if not still:
            return message
        return f"{message}; still executing (left running): {still}"

    async def run(self) -> RecipeRun:
        run = self._run  # mutated in place so `state` shows progress live — see __init__
        self._emit(f"recipe {self._recipe.header.name!r} started")

        # The initial step is inferred from topology — the one step no transition targets.
        # That inference is only valid because cycles are rejected (chart §2/§10); in a cyclic
        # chart every step is a target and this yields none.
        targets = {d for t in self._recipe.transitions for d in t.to_ids}
        initial = [s.id for s in self._recipe.steps if s.id not in targets]

        # [IEC 61512-1] item 1337 — a procedure is "a specification of a sequence of steps…
        # with **a defined beginning and end**". Singular. Both failures below were silent:
        #   * none  -> nothing activates, the loop never runs, and the run reported
        #             `completed` having done absolutely nothing;
        #   * several -> every one of them is started at once, on live equipment.
        if len(initial) != 1:
            run.status = "failed"
            run.error = (
                "a recipe needs exactly one initial step "
                "([IEC 61512-1] item 1337, 'a defined beginning and end'); "
                + (
                    "found none — every step is a transition target (a cycle?)"
                    if not initial
                    else f"found {len(initial)}: {sorted(initial)}"
                )
            )
            self._emit(f"recipe failed: {run.error}")
            return run  # nothing has been driven; no equipment was touched

        # Everything from here can touch the plant, so it runs under one guard. Without it a
        # failed OPC UA write escapes `run()` entirely and the task dies with no status —
        # which the (now removed) global timeout used to mask. `asyncio.CancelledError`
        # derives from BaseException, so cancellation still propagates untouched.
        try:
            await self._activate(initial[0], run)

            deadline = None if self._timeout is None else time.monotonic() + self._timeout
            while run.unfinished and not self._aborted:
                if deadline is not None and time.monotonic() > deadline:
                    run.status, run.error = "failed", "timed out"
                    self._emit("recipe timed out")
                    return run

                # Observe first, then fire: gate 1 must be settled from this pass's readings
                # before any receptivity is evaluated against them.
                await self._observe(run)
                if run.status == "failed":
                    return run

                if not await self._fire(run):
                    await asyncio.sleep(self._tick)  # nothing advanced — wait for the plant
        except Exception as exc:  # noqa: BLE001 - deliberate: see the comment above
            run.status = "failed"
            run.error = self._with_siblings(f"{type(exc).__name__}: {exc}", run)
            self._emit(f"recipe failed: {run.error}")
            return run

        if self._aborted:
            run.status = "aborted"
            # §7 — the operator must be told what an abort left behind. `abort()` itself
            # commands no PEA (§10 defers run-level commands), so anything mid-execution
            # keeps running and saying so is the least we owe them.
            still = self._still_executing(run)
            if still:
                run.error = f"aborted with steps still executing: {still}"
            self._emit(f"recipe aborted{f' — still executing: {still}' if still else ''}")
        elif not run.unfinished:
            run.status = "completed"
            self._emit(f"recipe {self._recipe.header.name!r} completed")
        return run

    # ── the two gates ───────────────────────────────────────────────────────────────

    async def _observe(self, run: RecipeRun) -> None:
        """Latch any running step that has reached a Final State — **gate 1**.

        Asynchronous because it reads the **plant**, not the snapshot cache: the latch is
        only as trustworthy as the reading behind it (`StepDriver.read_state`).
        """
        awaiting = (StepState.RUNNING, StepState.COMPLETING)
        interrupted: dict[str, ServiceState] = {}

        for step_id in [s for s, st in run.steps.items() if st in awaiting]:
            step = self._steps[step_id]

            # §11 — a PEA that drops while it holds an active step **fails the run**. Not
            # "held": HELD means an operator is deliberately intervening and the state is
            # *known*. A disconnect means we have lost observability of a running procedural
            # element — it may have completed, aborted or reset while we were blind, and we
            # cannot honestly claim to know. Checked before `state_of`, which cannot tell
            # "disconnected" from "no such service".
            if not self._driver.is_connected(step.pea_id):
                run.status = "failed"
                run.error = self._with_siblings(
                    f"lost connection to PEA {step.pea_id} while step {step_id!r} was running",
                    run, exclude={step_id},
                )
                self._emit(f"recipe failed: {run.error}")
                return

            # A direct read of the plant, not the snapshot — see `StepDriver.read_state`.
            state = await self._driver.read_state(step)
            if state is None:
                continue  # connected, but no reading for this service

            if not is_final(state):
                # Acting -> the PEA is working, keep waiting.
                if classify(state) is StateClass.INTERRUPTED:
                    # §7 levels 1-2. PAUSE is "a short-term stop… that does not require any
                    # additional shutdown or restarting actions"; HOLD "enables operator
                    # intervention… from which the normal running state can be manually
                    # resumed" ([61512-1] items 2341-2352). **Both are recoverable**, so the
                    # run waits indefinitely and does not fail — but it must *say so*.
                    interrupted[step_id] = state
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
                run.status = "failed"
                run.error = self._with_siblings(
                    f"step {step_id!r} terminated abnormally: {state.name}",
                    run, exclude={step_id},
                )
                self._emit(f"recipe failed: {run.error}")
                return

        # §10 — run status is **observed**, derived from its steps, not commanded. When the
        # operator resumes the service the run picks up again on its own, with no clock and
        # nothing failed. HELD outranks PAUSED: [2658-4:2022] §6.2.2 puts Hold at level 3 and
        # Pause at level 1, and §7 grades HOLD as the more severe intervention.
        # Replaced wholesale, never merged: a step that has resumed must drop out of the
        # map on the very next pass, the same way `status` returns to `running` by itself.
        run.interrupted = dict(interrupted)
        observed = "running"
        if any(s is ServiceState.HELD for s in interrupted.values()):
            observed = "held"
        elif interrupted:
            observed = "paused"
        if observed != run.status:
            detail = ", ".join(
                f"{sid} {st.name}" for sid, st in sorted(interrupted.items())
            )
            self._emit(f"recipe {observed}{f': {detail}' if detail else ''}")
        run.status = observed

    def _eligible(self, transition: Transition, run: RecipeRun) -> list[str] | None:
        """**Gate 1**, generalised over both procedure kinds (step model §3).

        Returns the continuous from-steps that are still running and must be sent
        `COMPLETE` — empty when every from-step has already terminated — or `None` when the
        transition is not eligible at all.

        * a **self-completing** from-step must have `TERMINATED`;
        * a **continuous** one is still `RUNNING`, because its receptivity is what ends it.

        A continuous step found already `TERMINATED` counts as terminated and advances
        directly: that means it ended without us asking (an operator, or an anomaly), and
        there is nothing left to `COMPLETE`.
        """
        pending: list[str] = []
        for from_id in transition.from_ids:
            state = run.steps.get(from_id)
            if state is StepState.TERMINATED:
                continue
            if state is StepState.RUNNING and not self._driver.is_self_completing(
                self._steps[from_id]
            ):
                pending.append(from_id)
                continue
            return None  # never started, still acting, already completing, or done
        return pending

    async def _fire(self, run: RecipeRun) -> bool:
        """Advance every transition whose gates hold. Returns whether anything happened.

        **Evaluate first, then act** — chart §8. Two things fall out of that split, and
        neither was true while the loop evaluated and mutated in one pass:

        * **OR arbitration is deliberate.** Transitions competing for the same from-step are
          resolved by list order, and at most one fires. Previously exclusivity was an
          *accident*: the first firing marked the step `DONE`, so a later transition's gate 1
          incidentally failed. Working by side effect is not the same as being correct.
        * **Nothing in a pass can enable anything else in that pass.** A step activated by an
          earlier firing is not eligible until the next pass. Otherwise a *continuous* step
          could be armed in the very pass that started it — sending `COMPLETE` milliseconds
          after `START`, with a negative `elapsed` (`now` predates its activation).
        """
        fired = False
        # Captured once. `_terminated_at` is written only by `_observe`, which has already
        # finished for this pass, and `_running_since` only by `_activate`, which now cannot
        # run before evaluation is complete — so `elapsed` can never come out negative.
        now = time.monotonic()

        # ── evaluate ── every transition against the state at the START of this pass, with
        # no mutation at all. Deciding first and acting second is what makes OR arbitration
        # deliberate rather than accidental, and it is why nothing a transition does can
        # change whether a later one in the same pass was enabled.
        ready: list[tuple[int, Transition, list[str] | None]] = []
        for index, transition in enumerate(self._recipe.transitions):
            # An armed transition awaits termination and is NEVER re-evaluated (chart §5(a)):
            # a receptivity falling false during COMPLETING must not strand the run with a
            # terminated step and no true branch.
            if index in self._armed:
                if all(
                    run.steps.get(f) is StepState.TERMINATED for f in transition.from_ids
                ):
                    ready.append((index, transition, None))
                continue

            pending = self._eligible(transition, run)
            if pending is None:
                continue

            # §9 — a transition is *enabled* when its last from-step became eligible: for a
            # self-completing step that is termination, for a continuous one it is
            # activation. One rule, from which `Elapsed` falls out as a **dwell** in the
            # first case and a **duration** in the second.
            elapsed = now - max(
                self._running_since[f] if f in pending else self._terminated_at[f]
                for f in transition.from_ids
            )
            context = EvalContext(self._state_of, self._value_of, elapsed)

            # ── gate 2 ── the author's receptivity.
            if not is_met(transition.condition, context):
                continue

            ready.append((index, transition, pending or None))

        # ── fire ── in priority order, **at most one transition per step** (chart §8).
        #
        # `MasterRecipe.transitions` is an ordered list, and that order *is* the priority:
        # the first eligible transition to claim a step wins, and every later one competing
        # for it is skipped. Exactly one branch is taken, so an OR-divergence can never be
        # indeterminate — which is SFC arbitration ([IEC 61131-3]), **not** GRAFCET
        # conformance. Corrected 2026-08-08 once [IEC 60848:2013] §6.2.3 was actually read:
        # GRAFCET does **not** call a non-exclusive chart "faulty and indeterminate" (that
        # was a secondary source overstating it). It says exclusive activation "is not
        # guaranteed from the structure" and puts the duty on the designer — and its own
        # EXAMPLE 2, "Priority sequence", encodes priority inside the receptivities. So we
        # hoist the same intent into the chart rather than contradicting the standard
        # (chart §8). The exclusivity *lint* stays deferred — a chart
        # with overlapping branches still runs deterministically here, it just has a
        # silently dead branch, which is an authoring smell rather than a safety problem.
        consumed: set[str] = set()
        # An **armed** transition holds its from-steps until it fires (chart §5(a)), even
        # across passes. Without this, a step that feeds an AND-join *and* has another
        # outgoing transition could be claimed, `RESET` and marked `DONE` by that other
        # transition — after which the join's "all TERMINATED" test can never be satisfied
        # again and the run hangs, with no timeout left to bound it.
        held_by_armed = {
            f for i in self._armed for f in self._recipe.transitions[i].from_ids
        }
        for index, transition, pending in ready:
            blocked = consumed if index in self._armed else consumed | held_by_armed
            if any(f in blocked for f in transition.from_ids):
                continue
            consumed.update(transition.from_ids)

            if pending:
                # For a continuous step the receptivity IS the completion criterion (step
                # model §2), so satisfying it means *ending* the step, not advancing past
                # it. Send `COMPLETE`, arm, and wait for termination.
                for from_id in pending:
                    await self._driver.complete(self._steps[from_id])
                    run.steps[from_id] = StepState.COMPLETING
                    self._emit(f"step {from_id} completing: Complete sent")
                self._armed.add(index)
            else:
                self._armed.discard(index)
                await self._advance(transition, run)
            fired = True
        return fired

    async def _advance(self, transition: Transition, run: RecipeRun) -> None:
        """The transition clears: deactivate its from-steps, activate its to-steps."""
        for from_id in transition.from_ids:
            # §5 / §12 item 0a — RESET on advance, not on termination. Until this moment the
            # service sat in its final state, which is what makes a terminated-but-not-yet-
            # advanced step visible on the PEA rather than only in our own run state.
            await self._driver.reset(self._steps[from_id])
            run.steps[from_id] = StepState.DONE

        # Emitted between deactivating the predecessors and activating the successors,
        # because that is the causal order: the transition clears, and *therefore* the next
        # steps start. Emitting it after activation made the operator timeline read
        # backwards ("s2 started" before "transition fired").
        self._emit(
            f"transition fired: {sorted(transition.from_ids)} -> "
            f"{sorted(transition.to_ids)}"
        )

        for to_id in transition.to_ids:
            if to_id != END:
                await self._activate(to_id, run)

    async def _activate(self, step_id: str, run: RecipeRun) -> None:
        step = self._steps[step_id]
        run.steps[step_id] = StepState.RUNNING
        self._running_since[step_id] = time.monotonic()
        try:
            await self._driver.start(step)
        except Exception:
            # It never started, so it must not be reported as "left running" by §7's
            # sibling list — that would tell the operator to go and stop equipment that
            # was never commanded. Un-track it and let the failure propagate.
            run.steps.pop(step_id, None)
            self._running_since.pop(step_id, None)
            raise
        # Emitted only once the step is genuinely under way: `driver.start` returns after
        # pre-flight, the handshake and await-started, so before this point "started" would
        # be a claim we cannot make.
        self._emit(
            f"step {step_id} started: {step.service} / procedure {step.procedure_id} "
            f"on PEA {step.pea_id}"
        )
