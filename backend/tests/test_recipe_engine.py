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
    """A minimal stand-in for the registry + control layer.

    `drive` puts a service straight into the state named by `on_start` (default EXECUTE);
    `finish()` walks it to a final state, which is what the engine latches. `reset` returns
    it to IDLE, exactly as `control.ensure_idle` would.
    """

    def __init__(self, on_start: str = "EXECUTE", continuous: set[str] | None = None) -> None:
        self.states: dict[tuple[int, str], str] = {}
        self.driven: list[str] = []
        self.reset: list[str] = []
        self.completed: list[str] = []
        self._on_start = on_start
        self.continuous = continuous or set()
        """Step ids whose procedure is *continuous* — they hold EXECUTE until told to stop."""

    async def drive(self, step: RecipeStep) -> None:
        self.driven.append(step.id)
        # A continuous procedure holds EXECUTE regardless of what `on_start` says: only an
        # explicit Complete ends it ([2658-4:2022] §6.2.3.2).
        start = "EXECUTE" if step.id in self.continuous else self._on_start
        self.states[(step.pea_id, step.service)] = start

    async def complete_step(self, step: RecipeStep) -> None:
        self.completed.append(step.id)
        self.states[(step.pea_id, step.service)] = ServiceState.COMPLETED.name

    def is_self_completing(self, step: RecipeStep) -> bool:
        return step.id not in self.continuous

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
    return RecipeEngine(
        recipe,
        drive_step=plant.drive,
        reset_step=plant.reset_step,
        complete_step=plant.complete_step,
        is_self_completing=plant.is_self_completing,
        state_of=plant.state_of,
        **kw,
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
    assert plant.reset == ["s1", "s2"]                  # §5 still mandatory


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
    assert plant.completed == ["s1"] and plant.reset == ["s1"]


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
