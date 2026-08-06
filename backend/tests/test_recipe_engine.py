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
    """A minimal stand-in for the registry + control layer.

    `drive` puts a service straight into the state named by `on_start` (default EXECUTE);
    `finish()` walks it to a final state, which is what the engine latches. `reset` returns
    it to IDLE, exactly as `control.ensure_idle` would.
    """

    def __init__(self, on_start: str = "EXECUTE") -> None:
        self.states: dict[tuple[int, str], str] = {}
        self.driven: list[str] = []
        self.reset: list[str] = []
        self._on_start = on_start

    async def drive(self, step: RecipeStep) -> None:
        self.driven.append(step.id)
        self.states[(step.pea_id, step.service)] = self._on_start

    async def reset_step(self, step: RecipeStep) -> None:
        self.reset.append(step.id)
        self.states[(step.pea_id, step.service)] = ServiceState.IDLE.name

    def state_of(self, pea_id: int, service: str) -> str | None:
        return self.states.get((pea_id, service))

    def finish(self, pea_id: int, state: str = "COMPLETED") -> None:
        self.states[(pea_id, "Stirring")] = state


def _step(step_id: str, pea_id: int) -> RecipeStep:
    return RecipeStep(id=step_id, pea_id=pea_id, service="Stirring", procedure_id=2)


def _linear(receptivity=None) -> MasterRecipe:
    """s1 (PEA 1) -> s2 (PEA 2) -> END.

    The receptivity defaults to `Elapsed(0)` — "nothing more to wait for". Under the two
    gates, completion is gate 1 and the author has nothing left to say. (`Always` is the
    proper spelling of this and arrives in unit 5.)
    """
    guard = receptivity or Elapsed(seconds=0.0)
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
    return RecipeEngine(
        recipe, drive_step=plant.drive, reset_step=plant.reset_step,
        state_of=plant.state_of, **kw,
    )


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
    assert plant.reset == ["s1", "s2"], plant.reset


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
        assert plant.reset == [], "reset before the transition fired"
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


def test_held_does_not_fail_the_run_it_waits() -> None:
    """§7 levels 1-2 — HELD is recoverable; the operator is meant to intervene. The run
    must wait, not fail. (Reporting it as `held` is unit 6.)"""
    plant = FakePlant(on_start="HELD")

    async def scenario():
        engine = _engine(_linear(), plant, tick=0.005, timeout=0.15)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        assert not task.done()
        assert plant.reset == []
        return await task

    run = asyncio.run(scenario())
    assert run.error == "timed out"  # waited, then hit the (unit-6) global timeout


# ── branch forms, under the two gates ───────────────────────────────────────────────

def _diamond() -> MasterRecipe:
    """s0 -> split -> {sA, sB concurrent} -> join -> END, over PEAs 1/2/3."""
    guard = Elapsed(seconds=0.0)
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
    assert set(plant.reset) == {"s0", "sA", "sB"}


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
            Transition(from_ids=["sX"], to_ids=[END], condition=Elapsed(seconds=0.0)),
            Transition(from_ids=["sY"], to_ids=[END], condition=Elapsed(seconds=0.0)),
        ],
    )
    engine = RecipeEngine(
        recipe, drive_step=plant.drive, reset_step=plant.reset_step,
        state_of=plant.state_of, value_of=lambda p, n: 20.0,   # cold
        tick=0.001, timeout=5.0,
    )
    run = asyncio.run(engine.run())
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
