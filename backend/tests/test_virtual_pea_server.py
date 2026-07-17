"""VirtualPEA over real OPC UA — the POL's M2/M3 mechanisms end to end.

No pytest-asyncio in this project, so each test drives one async scenario via
asyncio.run against a freshly started server on its own port.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from asyncua import Client, ua

from virtual_pea.codes import Command, ServiceState
from virtual_pea.server import VirtualPEA

HC30 = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"
SIEMENS_NS = "http://www.siemens.com/simatic-s7-opcua"
BASE = '"Stirring"."MTP"."ServiceControl".'

_PORT = iter(range(48070, 48090))  # a fresh port per test run to avoid TIME_WAIT


async def _with_server(scenario):
    endpoint = f"opc.tcp://127.0.0.1:{next(_PORT)}"
    pea = VirtualPEA(HC30, endpoint=endpoint)
    await pea.build()
    await pea.start()
    try:
        async with Client(endpoint) as client:
            idx = await client.get_namespace_index(SIEMENS_NS)
            return await scenario(client, idx)
    finally:
        await pea.stop()


def _node(client, idx, attr):
    return client.get_node(ua.NodeId(f'{BASE}"{attr}"', idx, ua.NodeIdType.String))


async def _write_word(client, idx, attr, value):
    await _node(client, idx, attr).write_value(
        ua.DataValue(ua.Variant(int(value), ua.VariantType.UInt32))
    )


async def _state(client, idx):
    return ServiceState(await _node(client, idx, "StateCur").read_value())


async def _settle():
    await asyncio.sleep(0.2)


def test_namespace_resolves_by_uri():
    """The peers' #1 interop failure is hardcoding an index; we resolve the URI."""
    async def scenario(client, idx):
        assert isinstance(idx, int)
        assert await _state(client, idx) == ServiceState.IDLE
        return True
    assert asyncio.run(_with_server(scenario))


def test_full_handshake_drives_idle_to_execute():
    async def scenario(client, idx):
        await _node(client, idx, "StateAutOp").write_value(True)
        await _settle()
        assert await _node(client, idx, "StateAutAct").read_value() is True

        await _node(client, idx, "SrcExtOp").write_value(True)
        await _settle()
        assert await _node(client, idx, "SrcExtAct").read_value() is True

        await _write_word(client, idx, "ProcedureExt", 1)
        await _settle()
        assert await _node(client, idx, "ProcedureReq").read_value() == 1

        await _write_word(client, idx, "CommandExt", int(Command.START))
        await _settle()
        assert await _state(client, idx) == ServiceState.EXECUTE
        assert await _node(client, idx, "ProcedureCur").read_value() == 1
        return True
    assert asyncio.run(_with_server(scenario))


def test_command_ext_is_ignored_before_the_handshake():
    """[§8.2.2.3] CommandExt is honoured only in Automatic + External.

    This is the failure the whole handshake exists to prevent: a command sent on
    the wrong channel is silently dropped. Starting from OFFLINE, START must not
    move the service.
    """
    async def scenario(client, idx):
        await _write_word(client, idx, "ProcedureExt", 1)  # no effect: wrong mode
        await _write_word(client, idx, "CommandExt", int(Command.START))
        await _settle()
        assert await _state(client, idx) == ServiceState.IDLE
        return True
    assert asyncio.run(_with_server(scenario))


def test_pol_receives_live_state_via_subscription():
    """The real M2 mechanism: the POL SUBSCRIBES to StateCur (does not poll) and

    is pushed datachange notifications. Drives the service while subscribed and
    checks the subscription delivered IDLE -> ... -> EXECUTE.
    """
    class Handler:
        def __init__(self):
            self.states = []

        def datachange_notification(self, node, val, data):
            if "StateCur" in str(node):
                self.states.append(ServiceState(val))

    async def scenario(client, idx):
        handler = Handler()
        sub = await client.create_subscription(50, handler)
        await sub.subscribe_data_change(_node(client, idx, "StateCur"))
        await asyncio.sleep(0.3)                       # initial value pushed

        await _node(client, idx, "StateAutOp").write_value(True)
        await _settle()
        await _node(client, idx, "SrcExtOp").write_value(True)
        await _settle()
        await _write_word(client, idx, "ProcedureExt", 1)
        await _settle()
        await _write_word(client, idx, "CommandExt", int(Command.START))
        await asyncio.sleep(0.3)
        await sub.delete()

        assert handler.states, "subscription delivered nothing"
        assert handler.states[0] == ServiceState.IDLE
        assert ServiceState.EXECUTE in handler.states
        return True
    assert asyncio.run(_with_server(scenario))


def test_self_completing_procedure_reaches_completed_without_complete():
    """Procedure 2 (Duration) is self-completing: EXECUTE is transient and the

    service advances to COMPLETED on its own, no Complete command sent (§6.2.2.1).
    """
    async def scenario(client, idx):
        await _node(client, idx, "StateAutOp").write_value(True)
        await _settle()
        await _node(client, idx, "SrcExtOp").write_value(True)
        await _settle()
        await _write_word(client, idx, "ProcedureExt", 2)   # Duration, self-completing
        await _settle()
        assert await _node(client, idx, "ProcedureReq").read_value() == 2
        await _write_word(client, idx, "CommandExt", int(Command.START))
        await _settle()
        # no COMPLETE issued — it must self-complete
        assert await _state(client, idx) == ServiceState.COMPLETED
        return True
    assert asyncio.run(_with_server(scenario))


def test_node_value_types_match_hc30_class_library():
    """Each ServiceControl node's OPC UA type == HC30's class-library declaration.

    Guards the audit fix (2026-07-17): a placeholder-UInt32 typing had mistyped
    every BOOL/STRING/BYTE attribute. One node per Table 13 type category.
    """
    expect = {
        "StateCur": ua.VariantType.UInt32,     # DWORD
        "CommandExt": ua.VariantType.UInt32,    # DWORD
        "StateOpOp": ua.VariantType.Boolean,    # BOOL (mode flag)
        "ProcParamApplyEn": ua.VariantType.Boolean,  # BOOL (was mistyped UInt32)
        "ReportValueFreeze": ua.VariantType.Boolean,
        "InteractAddInfo": ua.VariantType.String,    # STRING (was mistyped UInt32)
        "OSLevel": ua.VariantType.Byte,         # BYTE
        "WQC": ua.VariantType.Byte,             # BYTE (inherited from ServiceElement)
    }

    async def scenario(client, idx):
        for attr, want in expect.items():
            dv = await _node(client, idx, attr).read_data_value()
            assert dv.Value.VariantType == want, (attr, dv.Value.VariantType, want)
        return True
    assert asyncio.run(_with_server(scenario))


def test_start_refused_without_a_selected_procedure():
    """[§8.2.2.5] a valid non-zero procedure must be selected before Start."""
    async def scenario(client, idx):
        await _node(client, idx, "StateAutOp").write_value(True)
        await _settle()
        await _node(client, idx, "SrcExtOp").write_value(True)
        await _settle()
        # deliberately skip ProcedureExt -> ProcedureReq stays 0
        await _write_word(client, idx, "CommandExt", int(Command.START))
        await _settle()
        assert await _state(client, idx) == ServiceState.IDLE
        return True
    assert asyncio.run(_with_server(scenario))
