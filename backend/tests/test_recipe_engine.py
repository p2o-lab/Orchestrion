"""Recipe engine loop — unit tests with fakes (no live PEA).

Rewritten for the corrected step model (`docs/POL_Step_Model_ISA88.md`,
`docs/progress/010` unit 3). **The previous version of this file encoded the wrong
behaviour** and was rewritten rather than tweaked, per `010` §5:

  - it used `StateReached … "EXECUTE"` as receptivities, i.e. a transition firing *mid-step*
    — which §3 says cannot happen for a self-completing step;
  - `done` meant "a transition fired", not "the step terminated";
  - nothing ever reached a final state, so termination was never exercised at all.

Here a fake PEA walks IDLE -> EXECUTE -> COMPLETED so the two gates are really tested.
"""

from __future__ import annotations

import asyncio

from orchestrion.recipe.engine import RecipeEngine, StepState
from orchestrion.recipe.model import (
    END,
    Always,
    Elapsed,
    Header,
    MasterRecipe,
    RecipeStep,
    StateReached,
    Transition,
    ValueThreshold,
)
from orchestrion.state.codes import ServiceState


class FakePlant:
    """A fake `StepDriver` — a minimal stand-in for the registry + control layer.

    `start` puts a service straight into the state named by `on_start` (default EXECUTE);
    `finish()` walks it to a final state, which is what the engine latches. `reset` returns
    it to IDLE, exactly as `control.ensure_idle` would.

    The call-recording lists are named `driven` / `completed` / `was_reset` so none of them
    shadows a `StepDriver` method — `self.reset = []` would silently replace `reset()` and
    the engine's call would fail with "list is not callable".
    """

    def __init__(self, on_start: str = "EXECUTE", continuous: set[str] | None = None) -> None:
        self.states: dict[tuple[int, str], str] = {}
        self.driven: list[str] = []
        self.was_reset: list[str] = []
        self.completed: list[str] = []
        self._on_start = on_start
        self.continuous = continuous or set()
        """Step ids whose procedure is *continuous* — they hold EXECUTE until told to stop."""
        self.disconnected: set[int] = set()
        """PEA ids the POL has lost. Stated positively on purpose: an "ids still reachable"
        set has an empty-means-all sentinel, and `{only_pea} - {dropped}` is then empty —
        so dropping the *only* PEA read as "everything fine" and the run hung for ever."""

    # ── StepDriver: the four verbs ──────────────────────────────────────────────────

    async def start(self, step: RecipeStep) -> None:
        self.driven.append(step.id)
        # A continuous procedure holds EXECUTE regardless of what `on_start` says: only an
        # explicit Complete ends it ([2658-4:2022] §6.2.3.2).
        start = "EXECUTE" if step.id in self.continuous else self._on_start
        self.states[(step.pea_id, step.service)] = start

    async def complete(self, step: RecipeStep) -> None:
        self.completed.append(step.id)
        self.states[(step.pea_id, step.service)] = ServiceState.COMPLETED.name

    async def reset(self, step: RecipeStep) -> None:
        self.was_reset.append(step.id)
        self.states[(step.pea_id, step.service)] = ServiceState.IDLE.name

    async def read_state(self, step: RecipeStep) -> ServiceState | None:
        name = self.states.get((step.pea_id, step.service))
        return ServiceState[name] if name else None

    # ── StepDriver: the two questions ───────────────────────────────────────────────

    def is_self_completing(self, step: RecipeStep) -> bool:
        return step.id not in self.continuous

    def is_connected(self, pea_id: int) -> bool:
        return pea_id not in self.disconnected

    # ── test controls + the snapshot lookups the receptivities use ──────────────────

    def drop(self, pea_id: int) -> None:
        """Simulate losing this PEA; all others stay reachable."""
        self.disconnected.add(pea_id)

    def state_of(self, pea_id: int, service: str) -> str | None:
        return self.states.get((pea_id, service))

    def finish(self, pea_id: int, state: str = "COMPLETED") -> None:
        self.states[(pea_id, "Stirring")] = state


def _step(step_id: str, pea_id: int) -> RecipeStep:
    return RecipeStep(id=step_id, pea_id=pea_id, service="Stirring", procedure_id=2)


def _linear(receptivity=None) -> MasterRecipe:
    """s1 (PEA 1) -> s2 (PEA 2) -> END.

    The receptivity defaults to `Always` — "nothing more to wait for". Under the two gates,
    completion is gate 1 and the author has nothing left to say.
    """
    guard = receptivity or Always()
    return MasterRecipe(
        header=Header(name="linear"),
        steps=[_step("s1", 1), _step("s2", 2)],
        transitions=[
            Transition(from_ids=["s1"], to_ids=["s2"], condition=guard),
            Transition(from_ids=["s2"], to_ids=[END], condition=guard),
        ],
    )


def _engine(recipe: MasterRecipe, plant: FakePlant, **kw) -> RecipeEngine:
    kw.setdefault("tick", 0.001)
    kw.setdefault("timeout", 5.0)
    return RecipeEngine(recipe, driver=plant, state_of=plant.state_of, **kw)


# ── gate 1: a step is not done until a final state is latched ───────────────────────

def test_a_step_is_not_done_until_it_terminates() -> None:
    """The core of the correction. The service sits in EXECUTE; the receptivity is
    trivially true — and the run must still NOT advance, because gate 1 is unmet."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        assert not task.done(), "advanced while the service was still EXECUTE"
        assert plant.driven == ["s1"], "s2 must not start before s1 terminates"
        plant.finish(1)
        await asyncio.sleep(0.05)
        plant.finish(2)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed"
    assert run.done == {"s1", "s2"}


def test_the_latched_state_is_recorded() -> None:
    """§5 — the engine records *which* final state was reached, at the instant it saw it."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.02)
        plant.finish(1, "COMPLETED")
        await asyncio.sleep(0.02)
        plant.finish(2, "COMPLETED")
        return await task

    run = asyncio.run(scenario())
    assert run.terminal == {"s1": ServiceState.COMPLETED, "s2": ServiceState.COMPLETED}


def test_reset_is_sent_on_advance_for_every_step() -> None:
    """§5 / §12 0a — RESET is mandatory, and it is sent when the transition fires."""
    plant = FakePlant(on_start="COMPLETED")  # self-completing, finishes immediately
    run = asyncio.run(_engine(_linear(), plant).run())
    assert run.status == "completed"
    assert plant.was_reset == ["s1", "s2"], plant.was_reset


def test_reset_is_not_sent_while_the_step_is_merely_terminated() -> None:
    """A terminated-but-not-advanced step keeps its final state — that is what makes
    "S1 finished, waiting for …" visible on the PEA (§8)."""
    plant = FakePlant()
    never = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=80.0)

    async def scenario():
        engine = _engine(_linear(receptivity=never), plant, tick=0.005, timeout=0.2)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.02)
        plant.finish(1)
        await asyncio.sleep(0.05)
        assert plant.was_reset == [], "reset before the transition fired"
        assert plant.states[(1, "Stirring")] == "COMPLETED"
        return await task

    run = asyncio.run(scenario())
    assert run.status == "failed"  # times out: the receptivity never becomes true


# ── gate 2: the receptivity still has to hold ───────────────────────────────────────

def test_termination_alone_does_not_advance() -> None:
    """Both gates are required. The step terminates, but the receptivity is false."""
    plant = FakePlant(on_start="COMPLETED")
    never = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=80.0)

    async def scenario():
        engine = _engine(_linear(receptivity=never), plant, tick=0.005, timeout=0.2)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        assert plant.driven == ["s1"], "advanced on gate 1 alone"
        return await task

    run = asyncio.run(scenario())
    assert run.status == "failed" and run.error == "timed out"


def test_a_step_terminates_before_it_advances() -> None:
    """§8 — *terminated* is a real stage between running and done, not a bookkeeping
    detail. The event stream is where it shows: termination is emitted for a step
    **before** the transition that settles it fires."""
    plant = FakePlant()
    events: list[str] = []

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, on_event=events.append)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.02)
        plant.finish(1)
        await asyncio.sleep(0.02)
        plant.finish(2)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed"
    assert run.steps == {"s1": StepState.DONE, "s2": StepState.DONE}

    terminated = next(i for i, e in enumerate(events) if "s1 terminated: COMPLETED" in e)
    fired = next(i for i, e in enumerate(events) if "transition fired" in e)
    started_s2 = next(i for i, e in enumerate(events) if "s2 started" in e)
    assert terminated < fired < started_s2, events


# ── §9: Elapsed counts from when the transition became enabled ──────────────────────

def test_elapsed_counts_from_termination_not_from_start() -> None:
    """§9 — for a self-completing step, `Elapsed(x)` is a *dwell after it finishes*, not a
    duration from when it started. The step runs 60 ms, then the dwell must still apply."""
    plant = FakePlant()
    recipe = MasterRecipe(
        header=Header(name="dwell"),
        steps=[_step("s1", 1)],
        transitions=[
            Transition(from_ids=["s1"], to_ids=[END], condition=Elapsed(seconds=0.08))
        ],
    )

    async def scenario():
        engine = _engine(recipe, plant, tick=0.005)
        started = asyncio.get_running_loop().time()
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.06)
        plant.finish(1)                      # terminates only now
        run = await task
        return run, asyncio.get_running_loop().time() - started

    run, took = asyncio.run(scenario())
    assert run.status == "completed"
    # 60 ms running + 80 ms dwell: if elapsed had counted from the start it would have
    # fired at 80 ms total, well before 140 ms.
    assert took >= 0.135, took


# ── §7: abnormal termination fails the run ──────────────────────────────────────────

def test_abnormal_termination_fails_the_run() -> None:
    """STOPPED/ABORTED are Final States, so gate 1 would be satisfied — but items
    2355-2369 make them non-recoverable, so the run fails instead of advancing."""
    for state in ("STOPPED", "ABORTED"):
        plant = FakePlant(on_start=state)
        run = asyncio.run(_engine(_linear(), plant).run())
        assert run.status == "failed", state
        assert "s1" in run.error and state in run.error, run.error
        assert plant.driven == ["s1"], "a later step started after an abnormal termination"


# ── unit 6: exception handling, disconnect, no global timeout ───────────────────────

def test_held_is_reported_and_the_run_resumes_on_its_own() -> None:
    """§7 levels 1-2 — HOLD *"enables operator intervention… from which the normal running
    state can be manually resumed"*. So the run reports `held`, waits with **no clock**, and
    picks up again by itself when the operator resumes. Nothing fails."""
    plant = FakePlant(on_start="HELD")
    events: list[str] = []

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None, on_event=events.append)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        assert not task.done(), "a held run must not fail"
        assert plant.was_reset == []
        plant.finish(1)                      # operator resumes; the step runs to completion
        await asyncio.sleep(0.03)
        plant.finish(2)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert any("recipe held" in e for e in events), events


def test_a_held_run_names_which_step_is_held_and_clears_it_on_resume() -> None:
    """`status` says a run is held; `interrupted` says **where**.

    Without it nothing downstream can tell a held step from a working one: an interrupted
    step stays `RUNNING` in `steps`, because HELD is neither acting nor final and `_observe`
    falls through. That left the live chart pulsing "running" on the very step waiting for
    an operator — found in the 2026-09-06 audit.
    """
    plant = FakePlant(on_start="HELD")
    events: list[str] = []

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None, on_event=events.append)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        assert engine.state.status == "held"
        assert engine.state.interrupted == {"s1": ServiceState.HELD}
        # …and the step itself is still RUNNING, which is exactly why `interrupted` is needed
        assert engine.state.steps["s1"] is StepState.RUNNING

        plant.finish(1)                       # the operator releases the service
        await asyncio.sleep(0.03)
        # s1 drops out by itself, like `status` — the map is replaced each pass, not merged.
        # (s2 has started by now and this fake holds *every* step, so the map is not empty —
        # which is the sharper check: it proves replacement rather than a blanket clear.)
        assert "s1" not in engine.state.interrupted
        assert engine.state.interrupted == {"s2": ServiceState.HELD}
        plant.finish(2)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert run.interrupted == {}


def test_paused_is_reported_and_held_outranks_it() -> None:
    """PAUSE is the milder level (§7 level 1; [2658-4] §6.2.2 puts Pause at level 1 and Hold
    at level 3), so a run with both must report the more severe one."""
    plant = FakePlant(on_start="PAUSED")
    events: list[str] = []

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None, on_event=events.append)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.04)
        plant.states[(1, "Stirring")] = "HELD"      # escalates
        await asyncio.sleep(0.04)
        plant.finish(1)
        await asyncio.sleep(0.03)
        plant.finish(2)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert any("recipe paused" in e for e in events), events
    assert any("recipe held" in e for e in events), events


def test_a_disconnect_fails_the_run() -> None:
    """§11 — losing a PEA while it holds an active step is **not** "held". HELD means the
    state is known and an operator is intervening; a disconnect means we have lost
    observability and cannot honestly claim to know what the service is doing."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.03)
        plant.drop(1)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "failed"
    assert "lost connection to PEA 1" in run.error
    assert "'s1'" in run.error


def test_failure_names_the_siblings_it_leaves_running() -> None:
    """§7 — run-level propagation is a later increment, so a failed batch **can leave
    equipment running**. That is a known limitation, and the operator must be told rather
    than left to discover it."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_diamond(), plant, tick=0.005, timeout=None)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.02)
        plant.finish(1)                       # s0 terminates -> sA and sB both start
        await asyncio.sleep(0.03)
        plant.finish(2, "ABORTED")            # branch A dies; branch B is still executing
        return await task

    run = asyncio.run(scenario())
    assert run.status == "failed"
    assert "terminated abnormally: ABORTED" in run.error
    assert "still executing (left running): ['sB']" in run.error, run.error


def test_abort_names_what_it_leaves_running() -> None:
    """`abort()` commands no PEA (§10 defers propagation), so say what is still going."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.03)
        engine.abort()
        return await task

    run = asyncio.run(scenario())
    assert run.status == "aborted"
    assert "still executing: ['s1']" in run.error, run.error


def test_a_failing_drive_fails_the_run_instead_of_escaping() -> None:
    """`engine.py` had no `try`/`except` at all, so a failed OPC UA write escaped `run()`
    and the task died with no status — masked until now by the global timeout that §11
    removes. Removing the clock without this would have made the engine *less* safe."""
    class Broken(FakePlant):
        async def start(self, step: RecipeStep) -> None:
            raise RuntimeError("BadTypeMismatch writing CommandExt")

    plant = Broken()
    run = asyncio.run(_engine(_linear(), plant, tick=0.005, timeout=None).run())
    assert run.status == "failed"
    assert "RuntimeError" in run.error and "BadTypeMismatch" in run.error


def test_no_global_timeout_by_default() -> None:
    """§11 — real batches run for hours; the 60 s default was what turned a deliberately
    held batch into a false `failed`. A run with no timeout simply keeps waiting."""
    plant = FakePlant(on_start="IDLE")        # never terminates

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.1)
        assert not task.done(), "a run with no timeout must not fail on its own"
        engine.abort()
        return await task

    run = asyncio.run(scenario())
    assert run.status == "aborted"


# ── branch forms, under the two gates ───────────────────────────────────────────────

def _diamond() -> MasterRecipe:
    """s0 -> split -> {sA, sB concurrent} -> join -> END, over PEAs 1/2/3."""
    guard = Always()
    return MasterRecipe(
        header=Header(name="diamond"),
        steps=[_step("s0", 1), _step("sA", 2), _step("sB", 3)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=guard),
            Transition(from_ids=["sA", "sB"], to_ids=[END], condition=guard),
        ],
    )


def test_parallel_split_and_join() -> None:
    """The join's `And[COMPLETED(sA), COMPLETED(sB)]` is gone: both branches terminating
    **is** gate 1, so the receptivity has nothing left to say (chart §5)."""
    plant = FakePlant(on_start="COMPLETED")
    run = asyncio.run(_engine(_diamond(), plant).run())
    assert run.status == "completed"
    assert run.done == {"s0", "sA", "sB"}
    assert plant.driven[0] == "s0" and set(plant.driven) == {"s0", "sA", "sB"}
    assert set(plant.was_reset) == {"s0", "sA", "sB"}


def test_join_waits_for_the_slower_branch() -> None:
    plant = FakePlant()

    async def scenario():
        engine = _engine(_diamond(), plant, tick=0.005)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.02)
        plant.finish(1)                       # s0 terminates -> split
        await asyncio.sleep(0.02)
        plant.finish(2)                       # only branch A terminates
        await asyncio.sleep(0.04)
        assert not task.done(), "join fired before the second branch terminated"
        plant.finish(3)
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed" and run.done == {"s0", "sA", "sB"}


def test_or_divergence_selects_one_branch() -> None:
    """With the two gates, the shared "reached COMPLETED" is gate 1 and each branch now
    carries a *real* distinguishing receptivity — which is what makes it a selection."""
    plant = FakePlant(on_start="COMPLETED")
    hot = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=80.0)
    cold = ValueThreshold(pea_id=1, value_name="Temp", op="<=", threshold=80.0)
    recipe = MasterRecipe(
        header=Header(name="selection"),
        steps=[_step("s0", 1), _step("sX", 2), _step("sY", 3)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sX"], condition=hot),
            Transition(from_ids=["s0"], to_ids=["sY"], condition=cold),
            Transition(from_ids=["sX"], to_ids=[END], condition=Always()),
            Transition(from_ids=["sY"], to_ids=[END], condition=Always()),
        ],
    )
    run = asyncio.run(
        _engine(recipe, plant, value_of=lambda p, n: 20.0).run()   # cold
    )
    assert run.status == "completed"
    assert "sY" in plant.driven and "sX" not in plant.driven
    assert run.done == {"s0", "sY"}


def test_abort() -> None:
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.03)
        engine.abort()
        return await task

    run = asyncio.run(scenario())
    assert run.status == "aborted"
    assert run.steps["s1"] is StepState.RUNNING  # never terminated, never advanced


def test_times_out_if_stuck() -> None:
    plant = FakePlant(on_start="IDLE")   # never leaves IDLE, never terminates
    run = asyncio.run(_engine(_linear(), plant, tick=0.005, timeout=0.1).run())
    assert run.status == "failed" and run.error == "timed out"


# ── audit fixes ─────────────────────────────────────────────────────────────────────

def test_the_run_is_observable_while_it_runs() -> None:
    """**The audit's P1.** `engine.state` must be the same object `run()` mutates, so a
    caller can watch progress. It used to build its own and hand it back only at the end,
    which left `RunManager` holding a placeholder stuck at `running`/`{}` — making unit 6's
    held/paused reporting and §8's four step states invisible from outside."""
    plant = FakePlant()

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005)
        assert engine.state.steps == {}                     # nothing activated yet
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.03)

        live = engine.state
        assert live.steps == {"s1": StepState.RUNNING}, live.steps
        plant.finish(1)
        await asyncio.sleep(0.03)
        assert live.steps["s1"] is StepState.DONE          # progress visible mid-run
        assert live.terminal["s1"] is ServiceState.COMPLETED
        assert "s2" in live.steps

        plant.finish(2)
        returned = await task
        assert returned is live, "run() must return the very object it was mutating"
        return returned

    run = asyncio.run(scenario())
    assert run.status == "completed"


def test_held_status_is_visible_while_the_run_is_held() -> None:
    """The point of P1: unit 6 built held/paused reporting, and nothing outside the engine
    could see it."""
    plant = FakePlant(on_start="HELD")

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=None)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.04)
        assert engine.state.status == "held", engine.state.status
        plant.finish(1)
        await asyncio.sleep(0.03)
        plant.finish(2)
        return await task

    assert asyncio.run(scenario()).status == "completed"


def test_a_step_whose_start_fails_is_not_reported_as_left_running() -> None:
    """**The audit's P3 #1.** `_activate` marked a step RUNNING before awaiting
    `driver.start()`, so a step that never started was listed as equipment left running —
    telling the operator to go and stop something that was never commanded."""

    class FailsOnSecond(FakePlant):
        async def start(self, step: RecipeStep) -> None:
            if step.id == "s2":
                raise RuntimeError("pre-flight: Stirring is EXECUTE (in use)")
            await super().start(step)

    plant = FailsOnSecond(on_start="COMPLETED")
    run = asyncio.run(_engine(_linear(), plant, tick=0.005, timeout=None).run())
    assert run.status == "failed"
    assert "in use" in run.error
    assert "s2" not in run.error, run.error       # not claimed as left running
    assert "s2" not in run.steps


def test_an_armed_transition_holds_its_from_steps() -> None:
    """**The audit's P2b.** A step that feeds an AND-join *and* has another exit could be
    claimed, RESET and marked DONE by that other transition while the join was armed —
    after which the join's "all TERMINATED" test could never hold again and the run hung."""
    plant = FakePlant(on_start="COMPLETED", continuous={"sA"})
    hot = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=80.0)
    recipe = MasterRecipe(
        header=Header(name="armed-hold"),
        steps=[_step("s0", 1), _step("sA", 2), _step("sB", 3), _step("s4", 4)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=Always()),
            Transition(from_ids=["sA", "sB"], to_ids=["s4"], condition=hot),   # the join
            Transition(from_ids=["sB"], to_ids=[END], condition=Always()),     # competitor
            Transition(from_ids=["s4"], to_ids=[END], condition=Always()),
        ],
    )

    # The guard is true from the outset, so the join arms in the same pass that sB
    # terminates — which is the case the fix is about. (With it initially false the
    # competitor wins fairly, because the join simply is not ready; that leaves the join
    # permanently dead and is a *different* gap — see the deadlock note in `010`.)
    run = asyncio.run(
        _engine(recipe, plant, tick=0.005, timeout=2.0, value_of=lambda p, n: 95.0).run()
    )
    assert run.status == "completed", (run.status, run.error)
    assert "s4" in plant.driven, "the armed join never fired — sB was stolen"
    assert plant.completed == ["sA"], plant.completed   # only the continuous branch


# ── unit 8: OR arbitration — deliberate, not incidental ─────────────────────────────

def _selection(pea_id_x: int = 2, pea_id_y: int = 3) -> MasterRecipe:
    """s0 -> either sX (first listed) or sY. Both branch guards are `Always`, so **both are
    true at once** — which is precisely the case GRAFCET calls faulty and indeterminate, and
    which SFC resolves by branch priority (chart §8)."""
    return MasterRecipe(
        header=Header(name="selection"),
        steps=[_step("s0", 1), _step("sX", pea_id_x), _step("sY", pea_id_y)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sX"], condition=Always()),
            Transition(from_ids=["s0"], to_ids=["sY"], condition=Always()),
            Transition(from_ids=["sX"], to_ids=[END], condition=Always()),
            Transition(from_ids=["sY"], to_ids=[END], condition=Always()),
        ],
    )


def test_two_simultaneously_true_branches_take_exactly_one() -> None:
    """The heart of unit 8. Both receptivities hold in the same tick; the earlier-listed
    transition wins and the other is never taken — no indeterminacy, no double-start."""
    plant = FakePlant(on_start="COMPLETED")
    run = asyncio.run(_engine(_selection(), plant).run())
    assert run.status == "completed", run.error
    assert "sX" in plant.driven and "sY" not in plant.driven, plant.driven
    assert run.done == {"s0", "sX"}


def test_branch_priority_is_transition_list_order() -> None:
    """Priority *is* the order of `MasterRecipe.transitions` — no new model field. Swap the
    two branch transitions and the other branch wins, with nothing else changed."""
    recipe = _selection()
    recipe.transitions[0], recipe.transitions[1] = (
        recipe.transitions[1], recipe.transitions[0],
    )
    plant = FakePlant(on_start="COMPLETED")
    run = asyncio.run(_engine(recipe, plant).run())
    assert run.status == "completed", run.error
    assert "sY" in plant.driven and "sX" not in plant.driven, plant.driven


def test_a_continuous_step_is_completed_once_when_two_branches_fire_together() -> None:
    """Two branches off one *continuous* step with the **same** guard, both true at once.

    Only one `COMPLETE` may be sent. This held before unit 8 as well — but only because
    arming mutated the step to `COMPLETING`, which the next transition's `_eligible` then
    rejected. Same answer, reached by side effect. Now it is the arbitration rule doing it,
    and this test pins the guarantee rather than the accident.
    """
    plant = FakePlant(on_start="COMPLETED", continuous={"s0"})
    hot = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=80.0)
    recipe = MasterRecipe(
        header=Header(name="continuous-selection"),
        steps=[_step("s0", 1), _step("sX", 2), _step("sY", 3)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sX"], condition=hot),
            Transition(from_ids=["s0"], to_ids=["sY"], condition=hot),   # same guard!
            Transition(from_ids=["sX"], to_ids=[END], condition=Always()),
            Transition(from_ids=["sY"], to_ids=[END], condition=Always()),
        ],
    )
    run = asyncio.run(
        _engine(recipe, plant, value_of=lambda p, n: 95.0).run()
    )
    assert run.status == "completed", run.error
    assert plant.completed == ["s0"], "Complete must be sent exactly once"
    assert "sX" in plant.driven and "sY" not in plant.driven
    assert run.done == {"s0", "sX"}


def test_a_step_activated_this_pass_is_not_evaluated_until_the_next() -> None:
    """The real behaviour change: `elapsed` can no longer be negative.

    A step activated by an earlier firing used to be evaluated in that *same* pass, against
    a `now` captured **before** it was activated — so `now - _running_since[step]` came out
    negative. A continuous step with an always-true threshold could therefore be armed in
    the pass that started it, having "run" for minus-a-millisecond.

    Here `s1` is continuous with a guard that is already true, and `Elapsed(0.05)` on top:
    if it were armed in its activation pass the negative elapsed would make the dwell
    meaningless. It must run for the full 50 ms first.
    """
    plant = FakePlant(on_start="COMPLETED", continuous={"s1"})
    recipe = MasterRecipe(
        header=Header(name="same-pass"),
        steps=[_step("s0", 1), _step("s1", 2)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["s1"], condition=Always()),
            Transition(from_ids=["s1"], to_ids=[END], condition=Elapsed(seconds=0.05)),
        ],
    )

    async def scenario():
        started = asyncio.get_running_loop().time()
        run = await _engine(recipe, plant, tick=0.005).run()
        return run, asyncio.get_running_loop().time() - started

    run, took = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert plant.completed == ["s1"]
    assert took >= 0.05, took        # the dwell was measured from a real activation time


def test_parallel_branches_still_fire_together() -> None:
    """Arbitration must only bite on *conflict*. Two transitions with disjoint from-steps
    are not competing, so both still fire in the same pass — otherwise every AND-divergence
    would have been serialised."""
    plant = FakePlant(on_start="COMPLETED")
    recipe = MasterRecipe(
        header=Header(name="disjoint"),
        steps=[_step("s0", 1), _step("sA", 2), _step("sB", 3)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=Always()),
            Transition(from_ids=["sA"], to_ids=[END], condition=Always()),
            Transition(from_ids=["sB"], to_ids=[END], condition=Always()),
        ],
    )
    run = asyncio.run(_engine(recipe, plant).run())
    assert run.status == "completed", run.error
    assert run.done == {"s0", "sA", "sB"}
    assert set(plant.driven) == {"s0", "sA", "sB"}


# ── unit 5: `Always`, and the initial-step guard ────────────────────────────────────

def test_always_is_true_and_needs_no_context() -> None:
    """`Always` is the honest spelling of "completion is the only gate" (step model §3)."""
    from orchestrion.recipe.conditions import EvalContext, is_met

    ctx = EvalContext(lambda p, s: None, lambda p, n: None, 0.0)
    assert is_met(Always(), ctx) is True


def test_always_round_trips_through_the_discriminated_union() -> None:
    """Widening the union is additive: an existing recipe names its own type, so nothing
    stored can change meaning."""
    recipe = _linear()
    again = MasterRecipe.model_validate(recipe.model_dump())
    assert again.transitions[0].condition == Always()
    assert recipe.model_dump()["transitions"][0]["condition"] == {"type": "Always"}


def test_zero_initial_steps_fails_instead_of_completing_instantly() -> None:
    """chart §2 — a cycle leaves no step untargeted. The old loop then never ran and
    reported `completed` **having done nothing**; [61512-1] item 1337 requires a defined
    beginning, so this is now a failure."""
    plant = FakePlant(on_start="COMPLETED")
    looped = MasterRecipe(
        header=Header(name="cycle"),
        steps=[_step("s1", 1), _step("s2", 2)],
        transitions=[                       # s1 -> s2 -> s1: every step is a target
            Transition(from_ids=["s1"], to_ids=["s2"], condition=Always()),
            Transition(from_ids=["s2"], to_ids=["s1"], condition=Always()),
        ],
    )
    run = asyncio.run(_engine(looped, plant).run())
    assert run.status == "failed"
    assert "exactly one initial step" in run.error
    assert "found none" in run.error
    assert plant.driven == [], "a malformed recipe must not touch any equipment"


def test_several_initial_steps_fails_instead_of_starting_them_all() -> None:
    """The other silent failure: the engine used to activate **every** untargeted step —
    starting them all at once on live equipment."""
    plant = FakePlant(on_start="COMPLETED")
    forked = MasterRecipe(
        header=Header(name="two-beginnings"),
        steps=[_step("s1", 1), _step("s2", 2), _step("s3", 3)],
        transitions=[                       # nothing targets s1 or s2
            Transition(from_ids=["s1"], to_ids=["s3"], condition=Always()),
            Transition(from_ids=["s3"], to_ids=[END], condition=Always()),
        ],
    )
    run = asyncio.run(_engine(forked, plant).run())
    assert run.status == "failed"
    assert "found 2: ['s1', 's2']" in run.error, run.error
    assert plant.driven == []


def test_an_empty_recipe_fails_rather_than_completing() -> None:
    """No steps means no defined beginning either — and "completed" would be a lie."""
    plant = FakePlant()
    empty = MasterRecipe(header=Header(name="empty"), steps=[], transitions=[])
    run = asyncio.run(_engine(empty, plant).run())
    assert run.status == "failed" and "found none" in run.error


# ── unit 4: continuous procedures ───────────────────────────────────────────────────

def _hot(pea_id: int = 1) -> ValueThreshold:
    return ValueThreshold(pea_id=pea_id, value_name="Temp", op=">", threshold=80.0)


def test_continuous_step_never_terminates_on_its_own() -> None:
    """[2658-4:2022] §6.2.3.2 — a continuous procedure holds EXECUTE until told to stop.
    With a receptivity that never holds, the step must hang, not quietly finish."""
    plant = FakePlant(continuous={"s1", "s2"})
    run = asyncio.run(
        _engine(_linear(receptivity=_hot()), plant, tick=0.005, timeout=0.15).run()
    )
    assert run.status == "failed" and run.error == "timed out"
    assert plant.completed == [], "Complete was sent although the receptivity never held"


def test_continuous_step_is_completed_by_its_receptivity_then_advances() -> None:
    """§2's continuous column: receptivity -> COMPLETE -> await termination -> advance.
    The receptivity does not advance *past* a running service — it **ends** it."""
    plant = FakePlant(on_start="COMPLETED", continuous={"s1"})
    temp = {"v": 20.0}
    recipe = MasterRecipe(
        header=Header(name="continuous"),
        steps=[_step("s1", 1), _step("s2", 2)],
        transitions=[
            Transition(from_ids=["s1"], to_ids=["s2"], condition=_hot()),
            Transition(from_ids=["s2"], to_ids=[END], condition=Always()),
        ],
    )

    async def scenario():
        engine = _engine(recipe, plant, tick=0.005, value_of=lambda p, n: temp["v"])
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.04)
        assert plant.completed == [] and plant.driven == ["s1"], "advanced while cold"
        temp["v"] = 95.0                      # the completion criterion is met
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert plant.completed == ["s1"], plant.completed   # Complete sent exactly once
    assert plant.driven == ["s1", "s2"]
    assert plant.was_reset == ["s1", "s2"]              # §5 still mandatory


def test_an_armed_transition_is_not_re_evaluated() -> None:
    """chart §5(a) — once `COMPLETE` is sent the branch is latched. If the receptivity
    falls false while the service is COMPLETING, the run must still advance; re-evaluating
    would strand it with a terminated step and no true branch."""
    plant = FakePlant(continuous={"s1"})
    temp = {"v": 95.0}

    async def complete_then_go_cold(step: RecipeStep) -> None:
        await FakePlant.complete_step(plant, step)
        temp["v"] = 20.0            # receptivity falls false the instant Complete is sent

    plant.complete_step = complete_then_go_cold  # type: ignore[method-assign]

    recipe = MasterRecipe(
        header=Header(name="latched"),
        steps=[_step("s1", 1)],
        transitions=[Transition(from_ids=["s1"], to_ids=[END], condition=_hot())],
    )
    run = asyncio.run(
        _engine(recipe, plant, tick=0.005, timeout=1.0,
                value_of=lambda p, n: temp["v"]).run()
    )
    assert run.status == "completed", run.error
    assert plant.completed == ["s1"] and plant.was_reset == ["s1"]


def test_elapsed_on_a_continuous_step_is_a_duration_from_start() -> None:
    """§9 — one rule, two readings. For a continuous step the transition is enabled
    *immediately*, so `Elapsed(0.1)` means "run for 100 ms, then complete it"."""
    plant = FakePlant(continuous={"s1"})
    recipe = MasterRecipe(
        header=Header(name="duration"),
        steps=[_step("s1", 1)],
        transitions=[
            Transition(from_ids=["s1"], to_ids=[END], condition=Elapsed(seconds=0.1))
        ],
    )

    async def scenario():
        started = asyncio.get_running_loop().time()
        run = await _engine(recipe, plant, tick=0.005).run()
        return run, asyncio.get_running_loop().time() - started

    run, took = asyncio.run(scenario())
    assert run.status == "completed"
    assert plant.completed == ["s1"]
    assert took >= 0.1, took          # it really ran for the duration before being completed


def test_or_divergence_out_of_a_continuous_step_takes_one_branch() -> None:
    """chart §5(a) — the branch receptivities are jointly the completion criterion; the
    first to fire wins, `COMPLETE` is sent **once**, and the other branch never arms."""
    plant = FakePlant(on_start="COMPLETED", continuous={"s0"})
    recipe = MasterRecipe(
        header=Header(name="continuous-selection"),
        steps=[_step("s0", 1), _step("sX", 2), _step("sY", 3)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sX"], condition=_hot()),
            Transition(from_ids=["s0"], to_ids=["sY"], condition=Elapsed(seconds=10.0)),
            Transition(from_ids=["sX"], to_ids=[END], condition=Always()),
            Transition(from_ids=["sY"], to_ids=[END], condition=Always()),
        ],
    )
    run = asyncio.run(
        _engine(recipe, plant, tick=0.005, value_of=lambda p, n: 95.0).run()
    )
    assert run.status == "completed", run.error
    assert plant.completed == ["s0"], "Complete must be sent exactly once"
    assert "sX" in plant.driven and "sY" not in plant.driven
    assert run.done == {"s0", "sX"}


def test_mixed_kind_join_completes_only_the_continuous_branch() -> None:
    """chart §5(b) — the join's receptivity ends every *continuous* from-step; the
    self-completing one only has to have terminated. Item 1341 is satisfied at the instant
    the next step is initiated: all predecessors completed, and the condition true."""
    plant = FakePlant(on_start="COMPLETED", continuous={"sA"})  # sA continuous, sB not
    temp = {"v": 20.0}
    recipe = MasterRecipe(
        header=Header(name="mixed-join"),
        steps=[_step("s0", 1), _step("sA", 2), _step("sB", 3), _step("s4", 4)],
        transitions=[
            Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=Always()),
            Transition(from_ids=["sA", "sB"], to_ids=["s4"], condition=_hot()),
            Transition(from_ids=["s4"], to_ids=[END], condition=Always()),
        ],
    )

    async def scenario():
        engine = _engine(recipe, plant, tick=0.005, value_of=lambda p, n: temp["v"])
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        # sB (self-completing) has terminated; sA (continuous) is still running. The join
        # must NOT have fired — its receptivity is false.
        assert "s4" not in plant.driven, plant.driven
        assert plant.completed == []
        temp["v"] = 95.0
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed", run.error
    assert plant.completed == ["sA"], "only the continuous branch is Completed"
    assert set(plant.driven) == {"s0", "sA", "sB", "s4"}
    assert run.done == {"s0", "sA", "sB", "s4"}
