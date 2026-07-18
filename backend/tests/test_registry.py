"""PeaRegistry — persistent connect, snapshot, and health-drop on PEA death.

Runs everything on ONE asyncio loop (asyncio.run) with the VirtualPEA started and
stopped in-loop — deterministic, no TestClient/WebSocket/cross-loop fragility.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua.registry import PeaRegistry
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml_on_port(tmp_path: Path, port: int) -> Path:
    text = LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )
    dst = tmp_path / "pea.aml"
    dst.write_text(text, encoding="utf-8")
    return dst


def test_connect_snapshot_and_persist(tmp_path):
    aml = _aml_on_port(tmp_path, 48110)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            snap = await registry.connect(1, pea)
            assert snap.states["Stirring"] == "IDLE"
            assert registry.is_connected(1)

            # a second connect is idempotent (reuses the live connection)
            await registry.connect(1, pea)
            assert registry.is_connected(1)

            await registry.disconnect(1)
            assert not registry.is_connected(1)
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_streams_live_process_values(tmp_path):
    """The registry subscribes every value's V channel and streams live updates.

    HC30 exposes 4 process values; the VirtualPEA animates the 3 outgoing ones. Confirm
    they arrive in the snapshot (keyed by TagName) and that an analog one actually moves
    over time — i.e. it is a live subscription, not a one-shot read.
    """
    aml = _aml_on_port(tmp_path, 48112)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            await registry.connect(1, read_mtp(aml))

            # values arrive just after connect (subscribed last) — poll briefly.
            names = set()
            for _ in range(20):
                await asyncio.sleep(0.2)
                names = set(registry.snapshot(1).values)
                if {"HC30_FlowView_F13", "HC30_LevelView_L10", "HC30_Self_Full"} <= names:
                    break
            assert {"HC30_FlowView_F13", "HC30_LevelView_L10", "HC30_Self_Full"} <= names

            # an analog channel must change over time — proof of live streaming.
            samples = set()
            for _ in range(8):
                await asyncio.sleep(0.2)
                samples.add(round(registry.snapshot(1).values["HC30_FlowView_F13"], 3))
            assert len(samples) > 1
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_health_loop_drops_a_dead_connection(tmp_path):
    aml = _aml_on_port(tmp_path, 48111)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            await registry.connect(1, read_mtp(aml))
            assert registry.is_connected(1)

            await server.stop()  # the PEA goes away
            # the background health loop (2s) must notice and drop the entry
            for _ in range(20):
                await asyncio.sleep(0.5)
                if not registry.is_connected(1):
                    break
            assert not registry.is_connected(1)
        finally:
            await registry.shutdown()
        return True

    assert asyncio.run(scenario())
