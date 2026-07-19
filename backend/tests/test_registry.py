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


def test_snapshot_carries_analog_scaling_and_unit(tmp_path):
    """The registry reads each analog value's scale + unit once at connect (§7.5/§7.6)."""
    aml = _aml_on_port(tmp_path, 48114)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            await registry.connect(1, read_mtp(aml))
            meta = registry.snapshot(1).value_meta
            # the VirtualPEA seeds Flow as m³/h (Table 10 code 1349), range 0–50.
            flow = meta["HC30_FlowView_F13"]
            assert flow["unit"] == 1349
            assert flow["scl_min"] == 0.0 and flow["scl_max"] == 50.0
            # Level as % (code 1342), range 0–100.
            assert meta["HC30_LevelView_L10"]["unit"] == 1342
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_write_incoming_process_value_round_trips(tmp_path):
    """The POL writes a ProcessValueIn (§6.3.3) and reads it back on the live stream."""
    from orchestrion.opcua import control

    aml = _aml_on_port(tmp_path, 48113)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            await registry.connect(1, pea)
            conn = registry.connection(1)
            target = next(v for v in pea.process_values_in if v.name == "HC30_Target_Full")

            await control.write_process_value(conn, target, True)
            for _ in range(15):
                await asyncio.sleep(0.2)
                if registry.snapshot(1).values.get("HC30_Target_Full") is True:
                    break
            assert registry.snapshot(1).values.get("HC30_Target_Full") is True
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_state_transitions_are_logged_as_events(tmp_path):
    """M4 Step 2: the registry records each StateCur transition into the event log.

    Drives real transitions against the VirtualPEA (one loop) and asserts the log. The
    subscription may or may not sample a fast transient state (e.g. STARTING), so this
    asserts the durable endpoints of each transition (→ EXECUTE, → STOPPED), never a
    specific intermediate — robust to the sampling rate.
    """
    from orchestrion.opcua import control
    from orchestrion.state.codes import Command

    aml = _aml_on_port(tmp_path, 48115)

    async def _wait_state(registry, target: str, timeout=10.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if registry.snapshot(1).states.get("Stirring") == target:
                return True
            await asyncio.sleep(0.1)
        return False

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            await registry.connect(1, pea)
            service = pea.services[0]
            conn = registry.connection(1)

            await control.start_service(conn, service, procedure_id=1)  # Continous
            assert await _wait_state(registry, "EXECUTE")
            await control.command_service(conn, service, Command.STOP)
            assert await _wait_state(registry, "STOPPED")
            await asyncio.sleep(0.3)  # let the last datachange land

            # the log also holds the "connected" CONNECTION event (Step 3); isolate the
            # state transitions for this assertion.
            transitions = [
                e for e in registry.event_snapshot(1) if e["kind"] == "state_transition"
            ]
            assert transitions, "expected state-transition events to be logged"
            # each transition carries an arrow (the initial IDLE observation is NOT
            # logged — only real transitions are)
            assert all(" → " in str(e["message"]) for e in transitions)
            messages = [str(e["message"]) for e in transitions]
            assert any(m.endswith("→ EXECUTE") for m in messages), messages
            assert any(m.endswith("→ STOPPED") for m in messages), messages
            # the first transition leaves the initial IDLE state
            assert messages[0].startswith("Stirring: IDLE → "), messages
        finally:
            await registry.shutdown()
            await server.stop()
        return True

    assert asyncio.run(scenario())


def test_connect_and_disconnect_are_logged(tmp_path):
    """M4 Step 3: connect/disconnect are recorded as CONNECTION events, in order, and
    the log survives the disconnect (it is the session timeline, not per-connection)."""
    aml = _aml_on_port(tmp_path, 48116)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        registry = PeaRegistry()
        try:
            pea = read_mtp(aml)
            await registry.connect(1, pea)
            await registry.disconnect(1)

            events = registry.event_snapshot(1)  # kept after disconnect
            assert all(e["kind"] == "connection" for e in events)
            messages = [str(e["message"]) for e in events]
            assert "connected" in messages
            assert "disconnected" in messages
            assert messages.index("connected") < messages.index("disconnected")
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
            # the drop is logged as a CONNECTION event (M4 Step 3)
            messages = [str(e["message"]) for e in registry.event_snapshot(1)]
            assert "connection to the PEA was lost" in messages
        finally:
            await registry.shutdown()
        return True

    assert asyncio.run(scenario())
