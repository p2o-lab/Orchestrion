"""M4 Step 3: POL-initiated events (command, value write) recorded at the API layer.

The control endpoints are plain coroutines that record onto the **global** registry
(`api/live.registry`, the same object `api/control` imports). This drives them directly
against a real VirtualPEA in ONE asyncio loop — the API happy path cannot go through
TestClient (its per-request loop breaks the registry's persistent asyncua connection, see
journal 006), but calling the coroutines in-loop is exactly the production path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrion.api import control as control_api
from orchestrion.api import live as live_api
from orchestrion.api.control import StartRequest, ValueWrite
from orchestrion.db.models import Pea, Project
from orchestrion.mtp.parser import read_mtp
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml_on_port(tmp_path: Path, port: int) -> tuple[Path, str]:
    text = LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )
    dst = tmp_path / "pea.aml"
    dst.write_text(text, encoding="utf-8")
    return dst, text


def test_start_and_value_write_are_logged_at_the_api_layer(tmp_path):
    aml, aml_text = _aml_on_port(tmp_path, 48140)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        project = Project(name="Line")
        s.add(project)
        s.commit()
        s.refresh(project)
        row = Pea(project_id=project.id, name="Stirrer", aml_filename="HC30.aml",
                  aml_content=aml_text, endpoint_url="")
        s.add(row)
        s.commit()
        s.refresh(row)
        pea_id = row.id

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        # isolate the shared global registry from any other test's residue
        live_api.registry._entries.clear()
        live_api.registry._log.clear(pea_id)
        try:
            await live_api.registry.connect(pea_id, read_mtp(aml))

            # call the endpoint coroutines directly (fresh session each, as FastAPI would)
            with Session(engine) as s:
                await control_api.start(
                    pea_id, "Stirring", StartRequest(procedure_id=1), session=s
                )
            with Session(engine) as s:
                await control_api.write_value(
                    pea_id, "HC30_Target_Full", ValueWrite(value=True), session=s
                )

            events = live_api.registry.event_snapshot(pea_id)
            messages = [str(e["message"]) for e in events]
            kinds = {e["kind"] for e in events}
            assert any(m.startswith("Stirring: Start ") for m in messages), messages
            assert any(m.startswith("HC30_Target_Full :=") for m in messages), messages
            # first Start flips the PEA out of OFFLINE -> a mode event is logged (§6.2.1),
            # ordered BEFORE the Start command it enabled.
            assert "Stirring: → Automatic + External" in messages, messages
            assert {"command", "mode", "value_write"} <= kinds, kinds
            mode_i = next(i for i, e in enumerate(events) if e["kind"] == "mode")
            start_i = next(
                i for i, m in enumerate(messages) if m.startswith("Stirring: Start ")
            )
            assert mode_i < start_i, messages
        finally:
            await live_api.registry.disconnect(pea_id)
            live_api.registry._entries.clear()
            live_api.registry._log.clear(pea_id)
            await server.stop()
        return True

    assert asyncio.run(scenario())
