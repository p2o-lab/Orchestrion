"""PeaRegistry — live connection + snapshot + listener fan-out, vs the VirtualPEA."""

from __future__ import annotations

import asyncio
from pathlib import Path

from asyncua import Client, ua

from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua.registry import PeaRegistry
from orchestrion.state.codes import Command
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml_on_port(tmp_path: Path, port: int) -> Path:
    text = LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )
    dst = tmp_path / "pea.aml"
    dst.write_text(text, encoding="utf-8")
    return dst


async def _drive_to_execute(url: str, pea) -> None:
    control = pea.services[0].control
    async with Client(url) as drv:
        async def write(attr, value, vt):
            n = control.nodes[attr]
            idx = await drv.get_namespace_index(n.namespace)
            node = drv.get_node(ua.NodeId(n.identifier, idx, ua.NodeIdType.String))
            await node.write_value(ua.DataValue(ua.Variant(value, vt)))

        await write("StateAutOp", True, ua.VariantType.Boolean); await asyncio.sleep(0.15)
        await write("SrcExtOp", True, ua.VariantType.Boolean); await asyncio.sleep(0.15)
        await write("ProcedureExt", 1, ua.VariantType.UInt32); await asyncio.sleep(0.15)
        await write("CommandExt", int(Command.START), ua.VariantType.UInt32)
        await asyncio.sleep(0.15)


def test_registry_holds_live_state_and_fans_out(tmp_path):
    aml = _aml_on_port(tmp_path, 48094)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            snap = await registry.connect(1, pea)
            assert snap.states["Stirring"] == "IDLE"          # initial snapshot
            assert registry.is_connected(1)

            queue: asyncio.Queue = asyncio.Queue()
            registry.add_listener(1, queue)

            await _drive_to_execute(pea.endpoints[0].url, pea)

            # the listener was pushed the change, and the snapshot reflects it
            seen = []
            while not queue.empty():
                seen.append(queue.get_nowait())
            states = [m["state"] for m in seen if "state" in m]
            assert "EXECUTE" in states
            assert registry.snapshot(1).states["Stirring"] == "EXECUTE"
        finally:
            await registry.disconnect(1)
            assert not registry.is_connected(1)
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_connect_is_idempotent(tmp_path):
    aml = _aml_on_port(tmp_path, 48095)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            await registry.connect(1, pea)
            await registry.connect(1, pea)      # second call is a no-op, no raise
            assert registry.is_connected(1)
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())
