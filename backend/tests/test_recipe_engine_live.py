"""The engine against live VirtualPEA instances — the corrected step model.

**Rewritten at `010` unit 3, not tweaked** (`010` §5). The previous version was built
entirely on the *continuous* procedure with `StateReached … "EXECUTE"` receptivities, and
asserted `run.status == "completed"` **while asserting both services were still EXECUTE**.
That is the behaviour this correction removes: a step is `initiate + await termination`
(step model §1), so a run cannot be complete while its services are still running.

Every step here uses the **self-completing** procedure (`HC30_Stirring_Duration`), which is
what unit 3 handles; continuous steps need an explicit `COMPLETE` and arrive in unit 4.

`drive` and `reset` are wired the way unit 7 will wire them in production:
`ensure_idle` -> `start_service` -> `await_started`, and `command_service(RESET)`.

⚠ **Known limitation, recorded for unit 7.** `state_of` reads `registry.snapshot()`, a
200 ms subscription cache, while the VirtualPEA cycles a self-completing procedure in
~100 ms (`010` §7). On a **reused** service the cache can therefore still hold the previous
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
from orchestrion.recipe.engine import RecipeEngine
from orchestrion.recipe.model import (
    END,
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

NOW = Elapsed(seconds=0.0)
"""'Nothing further to wait for' — completion is gate 1, so the author has nothing to add.
`Always` is the proper spelling and arrives in unit 5."""


def _aml_on_port(tmp_path: Path, port: int, name: str) -> Path:
    dst = tmp_path / name
    dst.write_text(
        LOCAL_AML.read_text(encoding="utf-8").replace(
            "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
        ),
        encoding="utf-8",
    )
    return dst


class Plant:
    """N VirtualPEA instances in one registry, with production-shaped callbacks."""

    def __init__(self, amls: dict[int, Path]) -> None:
        self._amls = amls
        self.servers: list[VirtualPEA] = []
        self.registry = PeaRegistry()
        self.services: dict[int, dict[str, object]] = {}
        self.driven: list[str] = []
        self.reset: list[str] = []
        self.completed: list[str] = []
        self.self_completing: int = 0
        self.continuous: int = 0
        self.kinds: dict[int, dict[int, bool]] = {}
        """pea_id -> procedure_id -> IsSelfCompleting, straight off the parsed MTP
        ([2658-4:2022] Table 36 #4b). This is the production shape of the engine's
        `is_self_completing` callback."""

    async def start(self) -> None:
        for pea_id, aml in self._amls.items():
            server = VirtualPEA(aml)
            await server.build()
            await server.start()
            self.servers.append(server)
            pea = read_mtp(aml)
            await self.registry.connect(pea_id, pea)
            self.services[pea_id] = {sv.name: sv for sv in pea.services}
            stirring = pea.services[0]
            self.kinds[pea_id] = {
                p.procedure_id: p.is_self_completing for p in stirring.procedures
            }
            self.self_completing = next(
                p.procedure_id for p in stirring.procedures if p.is_self_completing
            )
            self.continuous = next(
                p.procedure_id for p in stirring.procedures if not p.is_self_completing
            )

    async def stop(self) -> None:
        await self.registry.shutdown()
        for server in self.servers:
            await server.stop()

    async def drive(self, step: RecipeStep) -> None:
        """Exactly the sequence step model §2 specifies: handshake + pre-flight, start,
        await-started."""
        conn = self.registry.connection(step.pea_id)
        service = self.services[step.pea_id][step.service]
        await control.ensure_idle(conn, service)
        await control.start_service(conn, service, step.procedure_id, step.params)
        await control.await_started(conn, service)
        self.driven.append(step.id)

    async def complete_step(self, step: RecipeStep) -> None:
        """[2658-4:2022] §6.2.3.2 — end a continuous procedure. `command_service` runs the
        mode handshake and unit 2's `CommandEn` guard, so a refused Complete raises."""
        conn = self.registry.connection(step.pea_id)
        service = self.services[step.pea_id][step.service]
        await control.command_service(conn, service, Command.COMPLETE)
        self.completed.append(step.id)

    def is_self_completing(self, step: RecipeStep) -> bool:
        return self.kinds[step.pea_id][step.procedure_id]

    async def reset_step(self, step: RecipeStep) -> None:
        conn = self.registry.connection(step.pea_id)
        service = self.services[step.pea_id][step.service]
        await control.command_service(conn, service, Command.RESET)
        self.reset.append(step.id)

    def state_of(self, pea_id: int, service: str) -> str | None:
        snap = self.registry.snapshot(pea_id)
        return snap.states.get(service) if snap else None

    def value_of(self, pea_id: int, name: str) -> float | None:
        snap = self.registry.snapshot(pea_id)
        if snap is None:
            return None
        raw = snap.values.get(name)
        return float(raw) if isinstance(raw, (int, float)) else None

    def engine(self, recipe: MasterRecipe, events: list[str], **kw) -> RecipeEngine:
        kw.setdefault("tick", 0.1)
        kw.setdefault("timeout", 40.0)
        return RecipeEngine(
            recipe,
            drive_step=self.drive,
            reset_step=self.reset_step,
            complete_step=self.complete_step,
            is_self_completing=self.is_self_completing,
            state_of=self.state_of,
            value_of=self.value_of,
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
        assert p.reset == ["s1", "s2"], p.reset          # §5 — RESET is mandatory
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
    """⭐ **The defect, dead.** Two steps in a row on the SAME service using the
    self-completing procedure — `010` §2's exact case.

    Before this correction: s1 finished into COMPLETED, s2's `Start` was silently dropped
    (not enabled in COMPLETED), the next transition asked "COMPLETED?", got yes, and the
    recipe reported success having run once.

    Now s2 cannot be dropped: pre-flight RESETs the finished service first, and unit 2's
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
        # Both steps were genuinely started — `drive` only appends after `await_started`
        # returned, and `start_service` would have raised had the command been refused.
        assert p.driven == ["s1", "s2"], p.driven
        assert p.reset == ["s1", "s2"], p.reset
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
        assert set(p.reset) == {"s0", "sA", "sB"}
        return run

    _run(plant, body)


def test_continuous_step_is_ended_by_its_receptivity(tmp_path):
    """⭐ **The other half of the defect.** `HC30_Stirring_Continous` holds EXECUTE for
    ever; `[2658-4:2022]` §6.2.3.2 says only an explicit `Complete` from the POL ends it.
    Before unit 4 the engine never sent one, so a continuous step deadlocked the recipe.

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
        assert p.reset == ["s1", "s2"], p.reset
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
