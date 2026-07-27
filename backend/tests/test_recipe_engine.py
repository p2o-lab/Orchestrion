"""Recipe engine loop + condition evaluation — unit tests with fakes (no live PEA)."""

from __future__ import annotations

import asyncio

from orchestrion.recipe.conditions import is_met
from orchestrion.recipe.engine import RecipeEngine
from orchestrion.recipe.model import END, Header, MasterRecipe, RecipeStep, StateReached, Transition


def _linear(state: str = "EXECUTE") -> MasterRecipe:
    """s1 (PEA 1) -> s2 (PEA 2) -> END, each advancing once its service reaches `state`."""
    return MasterRecipe(
        header=Header(name="linear"),
        steps=[
            RecipeStep(id="s1", pea_id=1, service="Stirring", procedure_id=1),
            RecipeStep(id="s2", pea_id=2, service="Stirring", procedure_id=1),
        ],
        transitions=[
            Transition(from_ids=["s1"], to_ids=["s2"],
                       condition=StateReached(pea_id=1, service="Stirring", state=state)),
            Transition(from_ids=["s2"], to_ids=[END],
                       condition=StateReached(pea_id=2, service="Stirring", state=state)),
        ],
    )


# ── conditions ────────────────────────────────────────────────────────────────

def test_is_met_state_reached() -> None:
    cond = StateReached(pea_id=1, service="Stirring", state="COMPLETED")
    assert is_met(cond, lambda p, s: "COMPLETED")
    assert not is_met(cond, lambda p, s: "EXECUTE")
    assert not is_met(cond, lambda p, s: None)  # not connected / not reporting yet


# ── engine loop (fakes) ─────────────────────────────────────────────────────────

def test_engine_runs_a_linear_recipe() -> None:
    states: dict[tuple[int, str], str] = {}
    events: list[str] = []

    async def drive(step: RecipeStep) -> None:
        # the fake PEA reaches EXECUTE as soon as the step is started
        states[(step.pea_id, step.service)] = "EXECUTE"

    def state_of(pea_id: int, service: str) -> str | None:
        return states.get((pea_id, service))

    engine = RecipeEngine(_linear(), drive_step=drive, state_of=state_of,
                          on_event=events.append, tick=0.001, timeout=5.0)
    run = asyncio.run(engine.run())

    assert run.status == "completed"
    assert run.done == {"s1", "s2"} and run.active == set()
    # both steps were driven, in order, and start/complete were emitted
    assert any("s1 started" in e for e in events)
    assert any("s2 started" in e for e in events)
    assert events[0].startswith("recipe 'linear' started")
    assert events[-1].startswith("recipe 'linear' completed")


def test_engine_waits_until_condition_is_met() -> None:
    states: dict[tuple[int, str], str] = {(1, "Stirring"): "IDLE", (2, "Stirring"): "IDLE"}

    async def drive(step: RecipeStep) -> None:
        pass  # PEA does NOT advance on its own

    def state_of(pea_id: int, service: str) -> str | None:
        return states.get((pea_id, service))

    async def scenario() -> object:
        engine = RecipeEngine(_linear(), drive_step=drive, state_of=state_of,
                              tick=0.005, timeout=5.0)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        # only s1 is active so far — the condition on s1 hasn't been met
        # now let PEA 1 reach EXECUTE, then PEA 2
        states[(1, "Stirring")] = "EXECUTE"
        await asyncio.sleep(0.05)
        states[(2, "Stirring")] = "EXECUTE"
        return await task

    run = asyncio.run(scenario())
    assert run.status == "completed" and run.done == {"s1", "s2"}


def test_engine_abort() -> None:
    async def drive(step: RecipeStep) -> None:
        pass

    async def scenario() -> object:
        engine = RecipeEngine(_linear(), drive_step=drive, state_of=lambda p, s: "IDLE",
                              tick=0.005, timeout=5.0)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)
        engine.abort()
        return await task

    run = asyncio.run(scenario())
    assert run.status == "aborted" and "s1" in run.active  # never advanced


def test_engine_times_out_if_stuck() -> None:
    async def drive(step: RecipeStep) -> None:
        pass

    engine = RecipeEngine(_linear(), drive_step=drive, state_of=lambda p, s: "IDLE",
                          tick=0.005, timeout=0.1)
    run = asyncio.run(engine.run())
    assert run.status == "failed" and run.error == "timed out"
