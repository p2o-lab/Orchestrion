"""M5.1 end-to-end: the engine runs a linear recipe across TWO live VirtualPEA instances.

Mirrors test_registry.py's single-loop pattern (VirtualPEAs started/stopped in-loop via
asyncio.run — no TestClient/cross-loop fragility). This is the "multiple VirtualPEA instances
as a plant" demo target from the design doc: two HC30 copies on different ports, orchestrated.
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
    And,
    Header,
    MasterRecipe,
    RecipeStep,
    StateReached,
    Transition,
    ValueThreshold,
)
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml_on_port(tmp_path: Path, port: int, name: str) -> Path:
    text = LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )
    dst = tmp_path / name
    dst.write_text(text, encoding="utf-8")
    return dst


def test_engine_orchestrates_two_virtual_peas(tmp_path):
    aml1 = _aml_on_port(tmp_path, 48120, "pea1.aml")
    aml2 = _aml_on_port(tmp_path, 48121, "pea2.aml")

    async def scenario():
        s1, s2 = VirtualPEA(aml1), VirtualPEA(aml2)
        for s in (s1, s2):
            await s.build()
            await s.start()
        registry = PeaRegistry()
        try:
            pea1, pea2 = read_mtp(aml1), read_mtp(aml2)
            await registry.connect(1, pea1)
            await registry.connect(2, pea2)

            # Resolve services by name per PEA (start_service needs the parsed Service).
            services = {
                1: {sv.name: sv for sv in pea1.services},
                2: {sv.name: sv for sv in pea2.services},
            }
            # A continuous procedure stays in EXECUTE, so an EXECUTE transition is deterministic.
            stirring = services[1]["Stirring"]
            cont = next(p.procedure_id for p in stirring.procedures if not p.is_self_completing)

            async def drive(step):
                conn = registry.connection(step.pea_id)
                service = services[step.pea_id][step.service]
                await control.start_service(conn, service, step.procedure_id, step.params)

            def state_of(pea_id: int, service: str):
                snap = registry.snapshot(pea_id)
                return snap.states.get(service) if snap else None

            events: list[str] = []
            recipe = MasterRecipe(
                header=Header(name="two-pea"),
                steps=[
                    RecipeStep(id="s1", pea_id=1, service="Stirring", procedure_id=cont),
                    RecipeStep(id="s2", pea_id=2, service="Stirring", procedure_id=cont),
                ],
                transitions=[
                    Transition(from_ids=["s1"], to_ids=["s2"],
                               condition=StateReached(pea_id=1, service="Stirring", state="EXECUTE")),
                    Transition(from_ids=["s2"], to_ids=[END],
                               condition=StateReached(pea_id=2, service="Stirring", state="EXECUTE")),
                ],
            )
            engine = RecipeEngine(recipe, drive_step=drive, state_of=state_of,
                                  on_event=events.append, tick=0.1, timeout=25.0)
            run = await engine.run()

            # The engine drove BOTH PEAs to EXECUTE, in sequence, and finished.
            assert run.status == "completed", (run.status, run.error, events)
            assert run.done == {"s1", "s2"}
            assert registry.snapshot(1).states["Stirring"] == "EXECUTE"
            assert registry.snapshot(2).states["Stirring"] == "EXECUTE"
            return run
        finally:
            await registry.shutdown()
            await s1.stop()
            await s2.stop()

    run = asyncio.run(scenario())
    assert run.status == "completed"


def test_engine_advances_on_a_live_value_threshold(tmp_path):
    """A transition driven by a ValueThreshold against a real, animated HC30 process value."""
    aml = _aml_on_port(tmp_path, 48122, "pea.aml")

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            await registry.connect(1, pea)
            services = {sv.name: sv for sv in pea.services}
            cont = next(p.procedure_id for p in services["Stirring"].procedures if not p.is_self_completing)

            # Discover a live numeric process value (don't hardcode HC30's names).
            vname, vval = None, None
            for _ in range(40):
                vals = registry.snapshot(1).values
                numeric = {n: v for n, v in vals.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                if numeric:
                    vname, vval = next(iter(numeric.items()))
                    break
                await asyncio.sleep(0.05)
            assert vname is not None, "no live numeric process value appeared"

            async def drive(step):
                await control.start_service(registry.connection(step.pea_id),
                                            services[step.service], step.procedure_id, step.params)

            def state_of(pea_id, service):
                snap = registry.snapshot(pea_id)
                return snap.states.get(service) if snap else None

            def value_of(pea_id, name):
                snap = registry.snapshot(pea_id)
                return snap.values.get(name) if snap else None

            # A threshold far below the value's scale → the condition holds once the live value
            # is actually read (proving value_of is wired to the live snapshot).
            recipe = MasterRecipe(
                header=Header(name="threshold"),
                steps=[RecipeStep(id="s1", pea_id=1, service="Stirring", procedure_id=cont)],
                transitions=[Transition(
                    from_ids=["s1"], to_ids=[END],
                    condition=ValueThreshold(pea_id=1, value_name=vname, op=">", threshold=vval - 1000.0),
                )],
            )
            engine = RecipeEngine(recipe, drive_step=drive, state_of=state_of, value_of=value_of,
                                  tick=0.1, timeout=15.0)
            run = await engine.run()
            assert run.status == "completed", (run.status, run.error)
            return run
        finally:
            await registry.shutdown()
            await server.stop()

    assert asyncio.run(scenario()).status == "completed"


def test_engine_parallel_diamond_across_three_peas(tmp_path):
    """M5.3: s0 -> split -> {sA, sB concurrent} -> join -> END across three live VirtualPEAs."""
    amls = [_aml_on_port(tmp_path, 48123 + i, f"pea{i}.aml") for i in range(3)]

    async def scenario():
        servers = [VirtualPEA(a) for a in amls]
        for s in servers:
            await s.build()
            await s.start()
        registry = PeaRegistry()
        try:
            peas = {}
            for i, a in enumerate(amls, start=1):
                pea = read_mtp(a)
                await registry.connect(i, pea)
                peas[i] = {sv.name: sv for sv in pea.services}
            cont = next(p.procedure_id for p in peas[1]["Stirring"].procedures if not p.is_self_completing)

            async def drive(step):
                await control.start_service(registry.connection(step.pea_id),
                                            peas[step.pea_id][step.service], step.procedure_id, step.params)

            def state_of(pea_id, service):
                snap = registry.snapshot(pea_id)
                return snap.states.get(service) if snap else None

            reach = lambda pid: StateReached(pea_id=pid, service="Stirring", state="EXECUTE")
            recipe = MasterRecipe(
                header=Header(name="diamond"),
                steps=[RecipeStep(id=sid, pea_id=pid, service="Stirring", procedure_id=cont)
                       for sid, pid in (("s0", 1), ("sA", 2), ("sB", 3))],
                transitions=[
                    Transition(from_ids=["s0"], to_ids=["sA", "sB"], condition=reach(1)),
                    Transition(from_ids=["sA", "sB"], to_ids=[END],
                               condition=And(conditions=[reach(2), reach(3)])),
                ],
            )
            run = await RecipeEngine(recipe, drive_step=drive, state_of=state_of,
                                     tick=0.1, timeout=25.0).run()

            assert run.status == "completed", (run.status, run.error)
            assert run.done == {"s0", "sA", "sB"}
            # all three PEAs were actually driven to EXECUTE (both branches + the source).
            assert all(registry.snapshot(i).states["Stirring"] == "EXECUTE" for i in (1, 2, 3))
            return run
        finally:
            await registry.shutdown()
            for s in servers:
                await s.stop()

    assert asyncio.run(scenario()).status == "completed"
