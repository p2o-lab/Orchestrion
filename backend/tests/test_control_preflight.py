"""Pre-flight + the CommandEn guard — `POL_Step_Model_ISA88.md` §4 and §4a.

Driven against the real VirtualPEA (same pattern as `test_control.py`): these are
protocol behaviours, and a fake connection would only assert that our own mock agrees
with itself. Ports 48140+ to stay clear of the other suites.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua.connection import PeaConnection
from orchestrion.opcua.control import (
    ServiceControlError,
    await_started,
    await_state,
    command_service,
    ensure_idle,
    read_command_en,
    require_command_enabled,
    start_service,
)
from orchestrion.state.codes import Command, ServiceState
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"

CONTINUOUS = 1        # HC30_Stirring_Continous — holds EXECUTE until told to Complete
SELF_COMPLETING = 2   # HC30_Stirring_Duration  — walks to COMPLETED on its own


def _aml(tmp_path: Path, port: int) -> Path:
    dst = tmp_path / "pea.aml"
    dst.write_text(
        LOCAL_AML.read_text(encoding="utf-8").replace(
            "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
        ),
        encoding="utf-8",
    )
    return dst


def _run(tmp_path, port, scenario):
    aml = _aml(tmp_path, port)

    async def main():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        try:
            pea = read_mtp(aml)
            async with PeaConnection(pea) as conn:
                return await scenario(conn, pea.services[0])
        finally:
            await server.stop()

    return asyncio.run(main())


# --- §4a  the CommandEn guard ------------------------------------------------------


def test_command_en_from_idle_allows_only_start(tmp_path):
    """[2658-4:2022 §6.2.2] the level model permits only lower->higher transitions, and
    Idle is level 5 — so Stop/Abort are not offered. Corroborated by [61512-1]'s NOTE
    (items 3452-3455) recommending STOP/ABORT be inhibited in IDLE."""
    async def scenario(conn, service):
        assert await conn.read_state(service) == ServiceState.IDLE
        assert await read_command_en(conn, service) == frozenset({Command.START})
        return True

    assert _run(tmp_path, 48140, scenario)


def test_reset_in_idle_is_refused_by_the_guard(tmp_path):
    """The guard turns a silently-discarded write into a named error."""
    async def scenario(conn, service):
        with pytest.raises(ServiceControlError) as exc:
            await command_service(conn, service, Command.RESET)
        message = str(exc.value)
        assert "RESET is not enabled" in message
        assert "IDLE" in message          # names the state
        assert "START" in message         # names what IS allowed
        return True

    assert _run(tmp_path, 48141, scenario)


def test_start_into_completed_is_refused(tmp_path):
    """**The defect, at its root.** A self-completing procedure ends in COMPLETED, where
    Start is not enabled — the PEA drops it silently and the recipe advances on a stale
    state. The guard now refuses it instead."""
    async def scenario(conn, service):
        await start_service(conn, service, SELF_COMPLETING)
        await await_state(
            conn, service, lambda s: s is ServiceState.COMPLETED, "COMPLETED", timeout=10.0
        )
        assert await read_command_en(conn, service) == frozenset({Command.RESET})
        with pytest.raises(ServiceControlError, match="START is not enabled"):
            await start_service(conn, service, SELF_COMPLETING)
        return True

    assert _run(tmp_path, 48142, scenario)


def test_require_command_enabled_passes_when_the_bit_is_set(tmp_path):
    async def scenario(conn, service):
        await require_command_enabled(conn, service, Command.START)  # must not raise
        return True

    assert _run(tmp_path, 48143, scenario)


# --- §4  the four pre-flight cases -------------------------------------------------


def test_ensure_idle_is_a_noop_when_already_idle(tmp_path):
    async def scenario(conn, service):
        await ensure_idle(conn, service)
        assert await conn.read_state(service) == ServiceState.IDLE
        return True

    assert _run(tmp_path, 48144, scenario)


def test_ensure_idle_resets_from_a_final_state(tmp_path):
    """[61512-1] Table B.2: COMPLETE "waits in the final state for a RESET command"."""
    async def scenario(conn, service):
        await start_service(conn, service, SELF_COMPLETING)
        await await_state(
            conn, service, lambda s: s is ServiceState.COMPLETED, "COMPLETED", timeout=10.0
        )
        await ensure_idle(conn, service)
        assert await conn.read_state(service) == ServiceState.IDLE
        return True

    assert _run(tmp_path, 48145, scenario)


def test_ensure_idle_resets_from_stopped(tmp_path):
    """The other two final states must work identically — STOPPED here."""
    async def scenario(conn, service):
        await start_service(conn, service, CONTINUOUS)
        await await_state(conn, service, lambda s: s is ServiceState.EXECUTE, "EXECUTE")
        await command_service(conn, service, Command.STOP)
        await await_state(conn, service, lambda s: s is ServiceState.STOPPED, "STOPPED")
        await ensure_idle(conn, service)
        assert await conn.read_state(service) == ServiceState.IDLE
        return True

    assert _run(tmp_path, 48146, scenario)


def test_ensure_idle_refuses_a_service_in_use(tmp_path):
    """§4 row 4: EXECUTE means somebody owns this service. Fail loudly, name the state."""
    async def scenario(conn, service):
        await start_service(conn, service, CONTINUOUS)
        await await_state(conn, service, lambda s: s is ServiceState.EXECUTE, "EXECUTE")
        with pytest.raises(ServiceControlError) as exc:
            await ensure_idle(conn, service)
        assert "EXECUTE" in str(exc.value)
        assert "in use" in str(exc.value)
        # and it did NOT seize the equipment
        assert await conn.read_state(service) == ServiceState.EXECUTE
        return True

    assert _run(tmp_path, 48147, scenario)


def test_ensure_idle_then_start_is_the_full_reuse_cycle(tmp_path):
    """Two consecutive runs of the *self-completing* procedure on one service — the exact
    case that once ran only once and still reported success."""
    async def scenario(conn, service):
        for _ in range(2):
            await ensure_idle(conn, service)
            await start_service(conn, service, SELF_COMPLETING)
            await await_started(conn, service)
            await await_state(
                conn, service, lambda s: s is ServiceState.COMPLETED,
                "COMPLETED", timeout=10.0,
            )
        assert await conn.read_state(service) == ServiceState.COMPLETED
        return True

    assert _run(tmp_path, 48148, scenario)


# --- §1 / §7  await-started ---------------------------------------------------------


def test_await_started_accepts_a_final_state(tmp_path):
    """The VirtualPEA publishes EXECUTE for one 50 ms scan and never publishes
    STARTING, so a self-completing procedure can reach COMPLETED between two polls.
    `await_started` must accept **any** state != IDLE, or it hangs on the normal case."""
    async def scenario(conn, service):
        await start_service(conn, service, SELF_COMPLETING)
        seen = await await_started(conn, service)
        assert seen is not ServiceState.IDLE
        return True

    assert _run(tmp_path, 48149, scenario)


def test_await_state_times_out_with_a_useful_message(tmp_path):
    async def scenario(conn, service):
        with pytest.raises(ServiceControlError) as exc:
            await await_state(
                conn, service, lambda s: s is ServiceState.EXECUTE,
                "EXECUTE", timeout=0.3,
            )
        assert "timed out waiting for EXECUTE" in str(exc.value)
        assert "still IDLE" in str(exc.value)   # says what it actually saw
        return True

    assert _run(tmp_path, 48150, scenario)
