"""Service control (M3) — the POL's handshake + commands, vs the VirtualPEA.

One asyncio loop (asyncio.run), VirtualPEA started/stopped in-loop — deterministic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua.connection import PeaConnection
from orchestrion.opcua.control import (
    ServiceControlError,
    command_service,
    ensure_automatic_external,
    select_procedure,
    set_parameter,
    start_service,
)
from orchestrion.state.codes import Command, ServiceState
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


def _aml(tmp_path: Path, port: int) -> Path:
    dst = tmp_path / "pea.aml"
    dst.write_text(
        LOCAL_AML.read_text(encoding="utf-8").replace(
            "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
        ),
        encoding="utf-8",
    )
    return dst


async def _wait_state(conn, service, target, timeout=10.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await conn.read_state(service) == target:
            return True
        await asyncio.sleep(0.1)
    return False


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


def test_start_service_runs_the_full_handshake(tmp_path):
    async def scenario(conn, service):
        assert await conn.read_state(service) == ServiceState.IDLE
        await start_service(conn, service, procedure_id=1)  # Continous
        assert await _wait_state(conn, service, ServiceState.EXECUTE)
        # the handshake really happened
        assert bool(await conn.read_control(service, "StateAutAct"))
        assert bool(await conn.read_control(service, "SrcExtAct"))
        assert int(await conn.read_control(service, "ProcedureCur")) == 1
        return True

    assert _run(tmp_path, 48130, scenario)


def test_stop_and_reset(tmp_path):
    async def scenario(conn, service):
        await start_service(conn, service, procedure_id=1)
        assert await _wait_state(conn, service, ServiceState.EXECUTE)
        await command_service(conn, service, Command.STOP)
        assert await _wait_state(conn, service, ServiceState.STOPPED)
        await command_service(conn, service, Command.RESET)
        assert await _wait_state(conn, service, ServiceState.IDLE)
        return True

    assert _run(tmp_path, 48131, scenario)


def test_abort_from_execute(tmp_path):
    async def scenario(conn, service):
        await start_service(conn, service, procedure_id=1)
        assert await _wait_state(conn, service, ServiceState.EXECUTE)
        await command_service(conn, service, Command.ABORT)
        assert await _wait_state(conn, service, ServiceState.ABORTED)
        return True

    assert _run(tmp_path, 48132, scenario)


def test_set_parameter_then_start_applies_the_value(tmp_path):
    async def scenario(conn, service):
        proc = next(p for p in service.procedures if p.procedure_id == 2)  # Duration
        assert proc.parameters, "Duration should have a parameter"
        param = proc.parameters[0]
        await start_service(conn, service, 2, values={param.name: 42.0})
        # the value is applied BEFORE Start, so VOut holds it now (proc 2 is
        # self-completing, so EXECUTE is transient — don't race it; check the value
        # and that the service actually ran through to COMPLETED).
        vout = float(await conn.read_value(param.data.nodes["VOut"]))
        assert abs(vout - 42.0) < 1e-6, vout
        assert await _wait_state(conn, service, ServiceState.COMPLETED)
        return True

    assert _run(tmp_path, 48134, scenario)


def test_out_of_range_parameter_is_rejected(tmp_path):
    async def scenario(conn, service):
        proc = next(p for p in service.procedures if p.procedure_id == 2)
        param = proc.parameters[0]
        # VMax is seeded at 1000 in the VirtualPEA; 99999 must not be accepted into VReq
        with pytest.raises(ServiceControlError):
            await set_parameter(conn, param, 99999.0)
        return True

    assert _run(tmp_path, 48135, scenario)


def test_ensure_auto_external_reports_only_real_changes(tmp_path):
    async def scenario(conn, service):
        # The VirtualPEA boots OFFLINE (§6.2.1 manufacturer default), so the first
        # handshake flips both channels and reports them...
        first = await ensure_automatic_external(conn, service)
        assert first == ["Automatic", "External"], first
        # ...and a second call is a no-op: already there, nothing changed.
        second = await ensure_automatic_external(conn, service)
        assert second == [], second
        return True

    assert _run(tmp_path, 48136, scenario)


def test_select_invalid_procedure_raises(tmp_path):
    async def scenario(conn, service):
        with pytest.raises(ServiceControlError):
            await select_procedure(conn, service, 999)
        return True

    assert _run(tmp_path, 48133, scenario)
