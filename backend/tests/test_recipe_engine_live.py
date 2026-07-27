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
from orchestrion.recipe.model import END, Header, MasterRecipe, RecipeStep, StateReached, Transition
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
