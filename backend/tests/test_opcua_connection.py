"""POL OPC UA connection — NodeId construction + a live read against the VirtualPEA."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from asyncua import Client, ua

from orchestrion.mtp.model import Access, IdentifierType, OpcUaNode
from orchestrion.mtp.parser import read_mtp
from orchestrion.opcua.connection import PeaConnection, build_node_id
from orchestrion.state.codes import Command, ServiceState, decode_state
from virtual_pea.server import VirtualPEA

LOCAL_AML = Path(__file__).parent.parent / "virtual_pea" / "HC30_Stirring_V8_local.aml"


# ── build_node_id: pure, all four [2658-1:2019] Table 3 identifier kinds ─────────

def _node(identifier, kind):
    return OpcUaNode(namespace="urn:x", identifier=identifier,
                     identifier_type=kind, access=Access.READ)


def test_build_node_id_string():
    nid = build_node_id(_node('"DB"."X"', IdentifierType.STRING), 3)
    assert nid.NodeIdType == ua.NodeIdType.String
    assert nid.Identifier == '"DB"."X"'
    assert nid.NamespaceIndex == 3


def test_build_node_id_numeric():
    nid = build_node_id(_node("42", IdentifierType.NUMERIC), 2)
    assert nid.NodeIdType == ua.NodeIdType.Numeric
    assert nid.Identifier == 42


def test_build_node_id_guid():
    g = "12345678-1234-1234-1234-123456789abc"
    nid = build_node_id(_node(g, IdentifierType.GUID), 1)
    assert nid.NodeIdType == ua.NodeIdType.Guid
    assert nid.Identifier == uuid.UUID(g)


def test_build_node_id_bytestring():
    nid = build_node_id(_node("AQID", IdentifierType.BYTE_ARRAY), 4)  # base64 -> 01 02 03
    assert nid.NodeIdType == ua.NodeIdType.ByteString
    assert nid.Identifier == b"\x01\x02\x03"


# ── live: the POL loop against the VirtualPEA ───────────────────────────────────

def _aml_on_port(tmp_path: Path, port: int) -> Path:
    """A copy of the local MTP with its endpoint on a unique port (both sides read it)."""
    text = LOCAL_AML.read_text(encoding="utf-8").replace(
        "opc.tcp://127.0.0.1:48050", f"opc.tcp://127.0.0.1:{port}"
    )
    dst = tmp_path / "pea.aml"
    dst.write_text(text, encoding="utf-8")
    return dst


def test_connect_resolves_namespace_by_uri_and_reads_state(tmp_path):
    aml = _aml_on_port(tmp_path, 48092)

    async def scenario():
        server = VirtualPEA(aml)                 # endpoint=None -> reads it from the .aml
        await server.build()
        await server.start()
        try:
            pea = read_mtp(aml)                   # the POL's own model, same file
            async with PeaConnection(pea) as conn:
                # namespace was resolved by URI (connect() would have raised otherwise)
                service = pea.services[0]
                assert await conn.read_state(service) == ServiceState.IDLE
                return True
        finally:
            await server.stop()

    assert asyncio.run(scenario())


async def _drive_to_execute(url: str, pea) -> None:
    """Drive the service IDLE->EXECUTE via a raw client (M3 write not built yet)."""
    control = pea.services[0].control
    async with Client(url) as drv:
        async def write(attr, value, vt):
            n = control.nodes[attr]
            idx = await drv.get_namespace_index(n.namespace)
            node = drv.get_node(ua.NodeId(n.identifier, idx, ua.NodeIdType.String))
            await node.write_value(ua.DataValue(ua.Variant(value, vt)))

        await write("StateAutOp", True, ua.VariantType.Boolean)
        await asyncio.sleep(0.15)
        await write("SrcExtOp", True, ua.VariantType.Boolean)
        await asyncio.sleep(0.15)
        await write("ProcedureExt", 1, ua.VariantType.UInt32)
        await asyncio.sleep(0.15)
        await write("CommandExt", int(Command.START), ua.VariantType.UInt32)
        await asyncio.sleep(0.15)


def test_subscription_delivers_live_state(tmp_path):
    """The M2 mechanism: the POL subscribes and is PUSHED StateCur changes."""
    aml = _aml_on_port(tmp_path, 48093)

    async def scenario():
        server = VirtualPEA(aml)
        await server.build()
        await server.start()
        seen: list[ServiceState] = []
        try:
            pea = read_mtp(aml)
            async with PeaConnection(pea) as conn:
                sub = await conn.subscribe_service_state(
                    lambda name, state: seen.append(state)
                )
                await asyncio.sleep(0.3)              # initial value pushed
                await _drive_to_execute(pea.endpoints[0].url, pea)
                await asyncio.sleep(0.3)
                await sub.delete()
        finally:
            await server.stop()

        assert seen, "subscription delivered nothing"
        assert seen[0] == ServiceState.IDLE          # initial push
        assert ServiceState.EXECUTE in seen          # live change pushed
        return True

    assert asyncio.run(scenario())
