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
    select_procedure,
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


async def _wait_state(conn, service, target, timeout=5.0):
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


def test_select_invalid_procedure_raises(tmp_path):
    async def scenario(conn, service):
        with pytest.raises(ServiceControlError):
            await select_procedure(conn, service, 999)
        return True

    assert _run(tmp_path, 48133, scenario)
