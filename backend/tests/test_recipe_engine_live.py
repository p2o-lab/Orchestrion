"""The engine against live VirtualPEA instances — the corrected step model.

**Rewritten, not tweaked.** The previous version was built
entirely on the *continuous* procedure with `StateReached … "EXECUTE"` receptivities, and
asserted `run.status == "completed"` **while asserting both services were still EXECUTE**.
That is the behaviour this correction removes: a step is `initiate + await termination`
(step model §1), so a run cannot be complete while its services are still running.

Both procedure kinds are covered: the **self-completing** `HC30_Stirring_Duration`, and the
**continuous** `HC30_Stirring_Continous`, which only ends when the POL sends `COMPLETE`.

`drive` and `reset` are wired the way production wires them:
`ensure_idle` -> `start_service` -> `await_started`, and `command_service(RESET)`.

**Known limitation.** `state_of` reads `registry.snapshot()`, a
200 ms subscription cache, while the VirtualPEA cycles a self-completing procedure in
~100 ms. On a **reused** service the cache can therefore still hold the previous
run's `COMPLETED` when the engine first observes the next step. The step model's latch (§5)
records the observation at a known instant, but it cannot be fresher than its source. These
tests assert what is unambiguous — that every step was really driven and really reset — and
the semantics themselves are pinned by the fakes in `test_recipe_engine.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua import control
from orchestrion.opcua.registry import PeaRegistry
from orchestrion.recipe.driver import PlantStepDriver
from orchestrion.recipe.engine import RecipeEngine
from orchestrion.recipe.model import (
    END,
    Always,
    Elapsed,
    Header,
    MasterRecipe,
    RecipeStep,
    Transition,
    ValueThreshold,
)
from orchestrion.state.codes import Command, ServiceState
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"

NOW = Always()
"""'Nothing further to wait for' — completion is gate 1 (step model §3), so the author has
nothing to add. Drawn `=1` in GRAFCET."""


def _aml_on_port(tmp_path: Path, port: int, name: str) -> Path:
    dst = tmp_path / name
    dst.write_text(
        LOCAL_AML.read_text(encoding="utf-8").replace(
            "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
        ),
        encoding="utf-8",
    )
    return dst


class RecordingDriver(PlantStepDriver):
    """The **production** driver, with the calls recorded.

    Subclassed rather than reimplemented on purpose: these tests are the only thing that
    exercises `recipe/driver.py` end to end, so they must run the real resolution and the
    real `control.*` sequences — not a parallel copy of them that could drift.
    """

    def __init__(self, registry: PeaRegistry, peas: dict[int, object]) -> None:
        super().__init__(registry, peas)
        self.driven: list[str] = []
        self.completed: list[str] = []
        self.was_reset: list[str] = []

    async def start(self, step: RecipeStep) -> None:
        await super().start(step)
        self.driven.append(step.id)

    async def complete(self, step: RecipeStep) -> None:
        await super().complete(step)
        self.completed.append(step.id)

    async def reset(self, step: RecipeStep) -> None:
        await super().reset(step)
        self.was_reset.append(step.id)


class Plant:
    """N VirtualPEA instances in one registry, driven by the production `StepDriver`."""

    def __init__(self, amls: dict[int, Path]) -> None:
        self._amls = amls
        self.servers: list[VirtualPEA] = []
        self.registry = PeaRegistry()
        self.peas: dict[int, object] = {}
        self.services: dict[int, dict[str, object]] = {}
        self.self_completing: int = 0
        self.continuous: int = 0
        self.driver: RecordingDriver | None = None

    async def start(self) -> None:
        for pea_id, aml in self._amls.items():
            server = VirtualPEA(aml)
            await server.build()
            await server.start()
            self.servers.append(server)
            pea = read_mtp(aml)
            await self.registry.connect(pea_id, pea)
            self.peas[pea_id] = pea
            self.services[pea_id] = {sv.name: sv for sv in pea.services}
            stirring = pea.services[0]
            self.self_completing = next(
                p.procedure_id for p in stirring.procedures if p.is_self_completing
            )
            self.continuous = next(
                p.procedure_id for p in stirring.procedures if not p.is_self_completing
            )
        self.driver = RecordingDriver(self.registry, self.peas)

    async def stop(self) -> None:
        await self.registry.shutdown()
        for server in self.servers:
            await server.stop()

    # Convenience passthroughs so the assertions stay readable.
    @property
    def driven(self) -> list[str]:
        return self.driver.driven

    @property
    def completed(self) -> list[str]:
        return self.driver.completed

    @property
    def was_reset(self) -> list[str]:
        return self.driver.was_reset

    def engine(self, recipe: MasterRecipe, events: list[str], **kw) -> RecipeEngine:
        kw.setdefault("tick", 0.1)
        kw.setdefault("timeout", 40.0)
        return RecipeEngine(
            recipe,
            driver=self.driver,
            state_of=self.driver.state_of,
            value_of=self.driver.value_of,
            on_event=events.append,
            **kw,
        )


def _run(plant: Plant, body):
    async def main():
        await plant.start()
        try:
            return await body(plant)
        finally:
            await plant.stop()

    return asyncio.run(main())


def _step(step_id: str, pea_id: int, procedure_id: int) -> RecipeStep:
    return RecipeStep(id=step_id, pea_id=pea_id, service="Stirring", procedure_id=procedure_id)


def test_linear_recipe_across_two_peas(tmp_path):
    """Two PEAs, self-completing steps. The run completes **and** no service is left
    running — the thing the old test explicitly could not assert."""
    plant = Plant({
        1: _aml_on_port(tmp_path, 48160, "pea1.aml"),
        2: _aml_on_port(tmp_path, 48161, "pea2.aml"),
    })

    async def body(p: Plant):
        proc = p.self_completing
        recipe = MasterRecipe(
            header=Header(name="two-pea"),
            steps=[_step("s1", 1, proc), _step("s2", 2, proc)],
            transitions=[
                Transition(from_ids=["s1"], to_ids=["s2"], condition=NOW),
                Transition(from_ids=["s2"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []
        run = await p.engine(recipe, events).run()
        assert run.status == "completed", (run.status, run.error, events)
        assert run.done == {"s1", "s2"}
        assert p.driven == ["s1", "s2"], p.driven
        assert p.was_reset == ["s1", "s2"], p.was_reset   # §5 — RESET is mandatory
        # No service left running: both were reset, so both are back at IDLE.
        for pea_id in (1, 2):
            conn = p.registry.connection(pea_id)
            service = p.services[pea_id]["Stirring"]
            await control.await_state(
                conn, service, lambda s: s is ServiceState.IDLE, "IDLE", timeout=10.0
            )
        return run

    _run(plant, body)


def test_two_consecutive_steps_on_one_pea(tmp_path):
    """**The defect, dead.** Two steps in a row on the SAME service using the
    self-completing procedure.

    Before this correction: s1 finished into COMPLETED, s2's `Start` was silently dropped
    (not enabled in COMPLETED), the next transition asked "COMPLETED?", got yes, and the
    recipe reported success having run once.

    Now s2 cannot be dropped: pre-flight RESETs the finished service first, and the
    `CommandEn` guard would raise rather than let a write vanish. Both steps really run.
    """
    plant = Plant({1: _aml_on_port(tmp_path, 48162, "pea1.aml")})

    async def body(p: Plant):
        proc = p.self_completing
        recipe = MasterRecipe(
            header=Header(name="same-pea-twice"),
            steps=[_step("s1", 1, proc), _step("s2", 1, proc)],   # same PEA, same service
            transitions=[
                Transition(from_ids=["s1"], to_ids=["s2"], condition=NOW),
                Transition(from_ids=["s2"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []
        run = await p.engine(recipe, events).run()
        assert run.status == "completed", (run.status, run.error, events)
        assert run.done == {"s1", "s2"}
        # Both steps were genuinely started — `start` only records after `await_started`
        # returned, and `start_service` would have raised had the command been refused.
        assert p.driven == ["s1", "s2"], p.driven
        assert p.was_reset == ["s1", "s2"], p.was_reset
        return run

    _run(plant, body)


def test_parallel_branches_across_three_peas(tmp_path):
    """M5.3's diamond, under the two gates: the join's hand-written
    `And[COMPLETED(sA), COMPLETED(sB)]` is gone — both branches terminating IS gate 1."""
    plant = Plant({
        1: _aml_on_port(tmp_path, 48163, "pea1.aml"),
        2: _aml_on_port(tmp_path, 48164, "pea2.aml"),
        3: _aml_on_port(tmp_path, 48165, "pea3.aml"),
    })

    async def body(p: Plant):
        proc = p.self_completing
        recipe = MasterRecipe(
            header=Header(name="diamond"),
            steps=[_step("s0", 1, proc), _step("sA", 2, proc), _step("sB", 3, proc)],
            transitions=[
                Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=NOW),
                Transition(from_ids=["sA", "sB"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []
        run = await p.engine(recipe, events).run()
        assert run.status == "completed", (run.status, run.error, events)
        assert run.done == {"s0", "sA", "sB"}
        assert p.driven[0] == "s0"
        assert set(p.driven) == {"s0", "sA", "sB"}
        assert set(p.was_reset) == {"s0", "sA", "sB"}
        return run

    _run(plant, body)


def test_continuous_step_is_ended_by_its_receptivity(tmp_path):
    """**The other half of the defect.** `HC30_Stirring_Continous` holds EXECUTE for
    ever; `[2658-4:2022]` §6.2.3.2 says only an explicit `Complete` from the POL ends it.
    The engine used to never send one, so a continuous step deadlocked the recipe.

    Here the receptivity IS the completion criterion (step model §2): after 1 s of real
    stirring the engine sends `Complete`, the service walks to `COMPLETED`, and only then
    does the next step start.
    """
    plant = Plant({
        1: _aml_on_port(tmp_path, 48168, "pea1.aml"),
        2: _aml_on_port(tmp_path, 48169, "pea2.aml"),
    })

    async def body(p: Plant):
        recipe = MasterRecipe(
            header=Header(name="continuous"),
            steps=[
                _step("s1", 1, p.continuous),          # holds EXECUTE until told to stop
                _step("s2", 2, p.self_completing),
            ],
            transitions=[
                # §9 — for a continuous step this is a *duration*: "stir for 1 s, then end it".
                Transition(from_ids=["s1"], to_ids=["s2"], condition=Elapsed(seconds=1.0)),
                Transition(from_ids=["s2"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []

        # While s1 is running it must really be in EXECUTE and stay there.
        conn = p.registry.connection(1)
        service = p.services[1]["Stirring"]

        task = asyncio.create_task(p.engine(recipe, events).run())
        await asyncio.sleep(0.6)
        assert not task.done()
        assert await conn.read_state(service) is ServiceState.EXECUTE, "continuous step ended early"
        assert p.completed == [], "Complete sent before the receptivity held"

        run = await task
        assert run.status == "completed", (run.status, run.error, events)
        assert p.completed == ["s1"], p.completed        # Complete sent, exactly once
        assert p.driven == ["s1", "s2"], p.driven        # s2 started only after s1 ended
        assert p.was_reset == ["s1", "s2"], p.was_reset
        return run

    _run(plant, body)


def test_killing_a_pea_mid_run_fails_the_run(tmp_path):
    """§11 — a PEA that drops while it holds an active step **fails** the run.

    The fake proves the logic; this proves the *wiring*: `is_connected` reads
    `registry.snapshot(id)`, and the registry's own health loop (2 s) is what removes the
    entry when the server goes away. Before this, `state_of` simply returned `None` and the
    run waited for ever with no indication why.
    """
    plant = Plant({
        1: _aml_on_port(tmp_path, 48170, "pea1.aml"),
        2: _aml_on_port(tmp_path, 48171, "pea2.aml"),
    })

    async def body(p: Plant):
        recipe = MasterRecipe(
            header=Header(name="kill-a-pea"),
            steps=[_step("s1", 1, p.continuous), _step("s2", 2, p.self_completing)],
            transitions=[
                # Long enough that the step is still running when we pull the plug.
                Transition(from_ids=["s1"], to_ids=["s2"], condition=Elapsed(seconds=60.0)),
                Transition(from_ids=["s2"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []
        task = asyncio.create_task(p.engine(recipe, events, timeout=30.0).run())

        # Let s1 reach EXECUTE, then kill its PEA outright.
        await asyncio.sleep(1.0)
        assert p.driven == ["s1"], p.driven
        dead = p.servers.pop(0)
        await dead.stop()

        run = await task
        assert run.status == "failed", (run.status, run.error, events)
        assert "lost connection to PEA 1" in run.error, run.error
        assert "'s1'" in run.error
        assert p.completed == [], "no Complete could have been sent to a dead PEA"
        return run

    _run(plant, body)


def test_value_threshold_gates_the_advance(tmp_path):
    """M5.2's live coverage, kept: a `ValueThreshold` on a real animated HC30 process
    value is gate 2. The step terminates first (gate 1), then this decides when to move."""
    plant = Plant({
        1: _aml_on_port(tmp_path, 48166, "pea1.aml"),
        2: _aml_on_port(tmp_path, 48167, "pea2.aml"),
    })

    async def body(p: Plant):
        proc = p.self_completing
        snap = p.registry.snapshot(1)
        name = next(
            n for n, v in snap.values.items() if isinstance(v, (int, float))
        )
        recipe = MasterRecipe(
            header=Header(name="threshold"),
            steps=[_step("s1", 1, proc), _step("s2", 2, proc)],
            transitions=[
                Transition(
                    from_ids=["s1"], to_ids=["s2"],
                    condition=ValueThreshold(
                        pea_id=1, value_name=name, op=">=", threshold=-1e9
                    ),
                ),
                Transition(from_ids=["s2"], to_ids=[END], condition=NOW),
            ],
        )
        events: list[str] = []
        run = await p.engine(recipe, events).run()
        assert run.status == "completed", (run.status, run.error, events)
        assert p.driven == ["s1", "s2"]
        return run

    _run(plant, body)
