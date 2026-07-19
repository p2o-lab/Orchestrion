"""Connect to one PEA and address its nodes — the POL's OPC UA client.

`PeaConnection` wraps an asyncua `Client` for a single `Pea`. On connect it resolves
every namespace URI the PEA's nodes use against the *live* server's namespace array
(never a hardcoded index), then serves reads/writes keyed by the `OpcUaNode` the parser
produced. Namespace-by-URI is the one thing this layer must get right (research §4.4).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import Callable
from types import TracebackType

from asyncua import Client, ua

from orchestrion.mtp.model import IdentifierType, OpcUaNode, Pea, Service, ValueObject
from orchestrion.state.codes import (
    Command,
    ServiceState,
    UnknownServiceState,
    decode_command_en,
    decode_state,
)

logger = logging.getLogger("orchestrion.opcua")


class OpcUaConnectionError(RuntimeError):
    """The POL could not connect to, or address a node on, the PEA."""


def build_node_id(node: OpcUaNode, namespace_index: int) -> ua.NodeId:
    """Build the OPC UA NodeId for a parsed node in an already-resolved namespace.

    Pure and testable: the namespace *index* must already have been resolved from the
    node's URI against the live server (that is `PeaConnection`'s job). The NodeId's
    identifier *kind* comes from the MTP's `IdentifierType` — [2658-1:2019] Table 3.
    """
    identifier = node.identifier
    kind = node.identifier_type

    if kind is IdentifierType.STRING:
        return ua.NodeId(identifier, namespace_index, ua.NodeIdType.String)
    if kind is IdentifierType.NUMERIC:
        try:
            numeric = int(identifier)
        except ValueError as exc:
            raise OpcUaConnectionError(
                f"numeric identifier {identifier!r} is not an integer"
            ) from exc
        return ua.NodeId(numeric, namespace_index, ua.NodeIdType.Numeric)
    if kind is IdentifierType.GUID:
        try:
            guid = uuid.UUID(identifier)
        except ValueError as exc:
            raise OpcUaConnectionError(
                f"GUID identifier {identifier!r} is not an RFC 4122 GUID"
            ) from exc
        return ua.NodeId(guid, namespace_index, ua.NodeIdType.Guid)
    if kind is IdentifierType.BYTE_ARRAY:
        return ua.NodeId(
            base64.b64decode(identifier), namespace_index, ua.NodeIdType.ByteString
        )
    raise OpcUaConnectionError(f"unsupported identifier type {kind!r}")


class PeaConnection:
    """A live OPC UA session with one PEA.

    Usage::

        async with PeaConnection(pea) as conn:
            state = await conn.read_value(some_node)
    """

    def __init__(self, pea: Pea, *, endpoint_index: int = 0) -> None:
        if not pea.endpoints:
            raise OpcUaConnectionError("PEA has no OPC UA endpoint to connect to")
        self._pea = pea
        self._url = pea.endpoints[endpoint_index].url
        self._client = Client(self._url)
        self._ns_index: dict[str, int] = {}   # namespace URI -> live server index
        self._vt_cache: dict[str, ua.VariantType] = {}  # identifier -> server value type
        self._connected = False

    @property
    def url(self) -> str:
        return self._url

    async def connect(self) -> None:
        """Open the session and resolve every namespace URI the PEA uses."""
        try:
            await self._client.connect()
        except (OSError, asyncio.TimeoutError, ua.UaError) as exc:
            # The PEA's server is unreachable/refusing (the common case when it is not
            # running) — a normal condition the caller handles, not a crash.
            raise OpcUaConnectionError(
                f"could not connect to {self._url}: {exc}"
            ) from exc
        self._connected = True
        try:
            for uri in self._pea_namespaces():
                # Resolve BY URI against the live server — never a file-supplied index.
                self._ns_index[uri] = await self._client.get_namespace_index(uri)
        except ua.UaError as exc:
            await self.disconnect()
            raise OpcUaConnectionError(
                f"namespace URI not registered on the server at {self._url}: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        if self._connected:
            self._connected = False
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001 — the server may already be gone
                pass

    async def is_alive(self) -> bool:
        """A real round-trip to the server — detects a PEA that has gone away.

        Reads the standard Server/ServerStatus/State node (ns0 i=2259), time-bounded
        so a half-open socket can never hang the caller; any failure or timeout means
        the OPC UA session is dead.
        """
        if not self._connected:
            return False
        try:
            await asyncio.wait_for(
                self._client.get_node(ua.NodeId(2259, 0)).read_value(), timeout=3.0
            )
            return True
        except (Exception, asyncio.TimeoutError):  # noqa: BLE001
            self._connected = False
            return False

    async def __aenter__(self) -> "PeaConnection":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()

    def node_id(self, node: OpcUaNode) -> ua.NodeId:
        """The live NodeId for a parsed node (namespace resolved by URI)."""
        index = self._ns_index.get(node.namespace)
        if index is None:
            raise OpcUaConnectionError(
                f"namespace {node.namespace!r} was not resolved at connect time"
            )
        return build_node_id(node, index)

    async def read_value(self, node: OpcUaNode) -> object:
        """Read a node's current value."""
        if not self._connected:
            raise OpcUaConnectionError("not connected")
        return await self._client.get_node(self.node_id(node)).read_value()

    async def read_state(self, service: Service) -> ServiceState:
        """Read and decode a service's current `StateCur` — [2658-4:2022] Table 14."""
        node = self._state_node(service)
        return decode_state(int(await self.read_value(node)))

    async def write_value(self, node: OpcUaNode, value: object) -> None:
        """Write a value using the server's declared type for that node.

        The server's value type (e.g. Boolean for a mode flag, UInt32 for a DWORD
        command/procedure word) is read once and cached; writing a bare Python int
        would send Int64 and the server would reject it (BadTypeMismatch).
        """
        if not self._connected:
            raise OpcUaConnectionError("not connected")
        n = self._client.get_node(self.node_id(node))
        vt = self._vt_cache.get(node.identifier)
        if vt is None:
            vt = await n.read_data_type_as_variant_type()
            self._vt_cache[node.identifier] = vt
        await n.write_value(ua.DataValue(ua.Variant(value, vt)))

    def control_node(self, service: Service, attr: str) -> OpcUaNode:
        """The ServiceControl node named `attr` (e.g. 'StateAutOp', 'CommandExt')."""
        if service.control is None or attr not in service.control.nodes:
            raise OpcUaConnectionError(
                f"service {service.name!r} has no ServiceControl node {attr!r}"
            )
        return service.control.nodes[attr]

    async def read_control(self, service: Service, attr: str) -> object:
        return await self.read_value(self.control_node(service, attr))

    async def write_control(self, service: Service, attr: str, value: object) -> None:
        await self.write_value(self.control_node(service, attr), value)

    async def subscribe_service_state(
        self,
        on_state: Callable[[str, ServiceState], None],
        *,
        on_command_en: Callable[[str, frozenset[Command]], None] | None = None,
        on_value: Callable[[str, object], None] | None = None,
        period_ms: int = 200,
    ) -> "StateSubscription":
        """Subscribe to every service's live `StateCur` (and optionally `CommandEn`),
        and — when `on_value` is given — every value object's live `V` channel.

        `on_state(service_name, ServiceState)` fires on each StateCur datachange — the
        M2 mechanism: the PEA pushes, the POL reacts (research §3, plan §3). The initial
        value is delivered once on subscribe. A StateCur the PEA sends that is not in
        Table 14 is logged and skipped, never crashes the handler.

        `on_value(value_name, raw)` fires on each datachange of a value object's `V`
        (§6.3 process values, #3 config params, #6 report values). Values are keyed by
        TagName, which is unique in the InstanceList ([2658-1:2022] Table 37 #19f), so a
        value modelled at both PEA and procedure level (shared RefID, §9.2.1) is one
        stream, not two. All value kinds share one subscription.
        """
        if not self._connected:
            raise OpcUaConnectionError("not connected")
        handler = _StateHandler(on_state, on_command_en, on_value)
        subscription = await self._client.create_subscription(period_ms, handler)

        for service in self._pea.services:
            if service.control is None:
                continue
            state_node = self._client.get_node(self.node_id(self._state_node(service)))
            handler.register(state_node.nodeid, service.name, _StateHandler.STATE)
            await subscription.subscribe_data_change(state_node)

            if on_command_en is not None and "CommandEn" in service.control.nodes:
                en_node = self._client.get_node(
                    self.node_id(service.control.nodes["CommandEn"])
                )
                handler.register(en_node.nodeid, service.name, _StateHandler.COMMAND_EN)
                await subscription.subscribe_data_change(en_node)

        if on_value is not None:
            for name, value in self._all_value_objects().items():
                # The live-value channel differs by element type: IndicatorElement
                # (*View) and InputElement (*ProcessValue) carry `V`; ParameterElement
                # (*ServParam — config/procedure params) carries the applied `VOut`
                # from controlled value assignment (§8.1.3), never a plain `V`.
                node = value.data.nodes.get("V") or value.data.nodes.get("VOut")
                if node is None:
                    continue  # a value with no readable channel — nothing to stream
                v_node = self._client.get_node(self.node_id(node))
                handler.register(v_node.nodeid, name, _StateHandler.VALUE)
                await subscription.subscribe_data_change(v_node)

        return StateSubscription(subscription)

    async def read_value_metadata(self) -> dict[str, dict[str, object]]:
        """Read each value's scaling + unit once — [2658-3:2020] §7.5/§7.6.

        Returns `name -> {"unit": int, "scl_min": float, "scl_max": float}` for values
        that carry those channels (analog Views). These are **design config**, not live
        signals (§7.5: "cannot be changed at runtime"), so they are read once at connect
        rather than subscribed. `unit` is the [Table 10] code; the UI maps it to a symbol.
        """
        meta: dict[str, dict[str, object]] = {}
        for name, value in self._all_value_objects().items():
            nodes = value.data.nodes
            entry: dict[str, object] = {}
            if "VUnit" in nodes:
                entry["unit"] = int(await self.read_value(nodes["VUnit"]))
            if "VSclMin" in nodes:
                entry["scl_min"] = float(await self.read_value(nodes["VSclMin"]))
            if "VSclMax" in nodes:
                entry["scl_max"] = float(await self.read_value(nodes["VSclMax"]))
            if entry:
                meta[name] = entry
        return meta

    def _all_value_objects(self) -> dict[str, ValueObject]:
        """Every value object the PEA exposes, keyed by TagName (deduped).

        PEA-wide process values (§6.3), per-service config params (#3), and per-procedure
        report/process values (#6/#7/#8). A value at both PEA and procedure level shares
        a TagName, so `setdefault` keeps it a single entry.
        """
        result: dict[str, ValueObject] = {}
        for value in (*self._pea.process_values_in, *self._pea.process_values_out):
            result.setdefault(value.name, value)
        for service in self._pea.services:
            for value in service.config_parameters:
                result.setdefault(value.name, value)
            for procedure in service.procedures:
                for value in (
                    *procedure.report_values,
                    *procedure.process_values_in,
                    *procedure.process_values_out,
                ):
                    result.setdefault(value.name, value)
        return result

    def _state_node(self, service: Service) -> OpcUaNode:
        if service.control is None or "StateCur" not in service.control.nodes:
            raise OpcUaConnectionError(
                f"service {service.name!r} has no StateCur node to read"
            )
        return service.control.nodes["StateCur"]

    def _pea_namespaces(self) -> set[str]:
        """Every distinct namespace URI referenced by any node the POL will address.

        Not just the ServiceControl: procedure parameters (M3-3b), config parameters,
        report values and process values are all addressed too, so every one's namespace
        must be resolved at connect (a URI in an unresolved namespace fails at use). HC30
        keeps everything in one namespace, which had masked the narrower earlier scope.
        """
        uris: set[str] = set()

        def add(nodes: dict[str, OpcUaNode]) -> None:
            for opc_node in nodes.values():
                uris.add(opc_node.namespace)

        for service in self._pea.services:
            if service.control is not None:
                add(service.control.nodes)
            for value in service.config_parameters:
                add(value.data.nodes)
            for procedure in service.procedures:
                for parameter in procedure.parameters:
                    add(parameter.data.nodes)
                for value in (
                    *procedure.report_values,
                    *procedure.process_values_in,
                    *procedure.process_values_out,
                ):
                    add(value.data.nodes)
        for value in (*self._pea.process_values_in, *self._pea.process_values_out):
            add(value.data.nodes)
        return uris


class StateSubscription:
    """A handle to an active state subscription; call `delete()` to stop it."""

    def __init__(self, subscription) -> None:
        self._subscription = subscription

    async def delete(self) -> None:
        await self._subscription.delete()


class _StateHandler:
    """asyncua datachange handler: routes a monitored node to a decoded callback."""

    STATE = "state"
    COMMAND_EN = "command_en"
    VALUE = "value"

    def __init__(
        self,
        on_state: Callable[[str, ServiceState], None],
        on_command_en: Callable[[str, frozenset[Command]], None] | None,
        on_value: Callable[[str, object], None] | None = None,
    ) -> None:
        self._on_state = on_state
        self._on_command_en = on_command_en
        self._on_value = on_value
        self._routes: dict[str, tuple[str, str]] = {}  # nodeid str -> (name, kind)

    def register(self, nodeid: ua.NodeId, service_name: str, kind: str) -> None:
        self._routes[nodeid.to_string()] = (service_name, kind)

    def status_change_notification(self, status) -> None:
        # asyncua calls this on subscription status changes; the WS layer detects a
        # lost connection via its own liveness check, so this is a quiet no-op.
        pass

    def datachange_notification(self, node, value, data) -> None:
        route = self._routes.get(node.nodeid.to_string())
        if route is None:
            return
        name, kind = route
        if kind == self.STATE:
            try:
                state = decode_state(int(value))
            except UnknownServiceState as exc:
                logger.warning("%s: %s", name, exc)
                return
            self._on_state(name, state)
        elif kind == self.COMMAND_EN and self._on_command_en is not None:
            self._on_command_en(name, decode_command_en(int(value)))
        elif kind == self.VALUE and self._on_value is not None:
            self._on_value(name, value)
