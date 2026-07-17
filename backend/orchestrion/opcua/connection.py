"""Connect to one PEA and address its nodes — the POL's OPC UA client.

`PeaConnection` wraps an asyncua `Client` for a single `Pea`. On connect it resolves
every namespace URI the PEA's nodes use against the *live* server's namespace array
(never a hardcoded index), then serves reads/writes keyed by the `OpcUaNode` the parser
produced. Namespace-by-URI is the one thing this layer must get right (research §4.4).
"""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import Callable
from types import TracebackType

from asyncua import Client, ua

from orchestrion.mtp.model import IdentifierType, OpcUaNode, Pea, Service
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
        self._connected = False

    @property
    def url(self) -> str:
        return self._url

    async def connect(self) -> None:
        """Open the session and resolve every namespace URI the PEA uses."""
        await self._client.connect()
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
            await self._client.disconnect()
            self._connected = False

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

    async def subscribe_service_state(
        self,
        on_state: Callable[[str, ServiceState], None],
        *,
        on_command_en: Callable[[str, frozenset[Command]], None] | None = None,
        period_ms: int = 200,
    ) -> "StateSubscription":
        """Subscribe to every service's live `StateCur` (and optionally `CommandEn`).

        `on_state(service_name, ServiceState)` fires on each StateCur datachange — the
        M2 mechanism: the PEA pushes, the POL reacts (research §3, plan §3). The initial
        value is delivered once on subscribe. A StateCur the PEA sends that is not in
        Table 14 is logged and skipped, never crashes the handler.
        """
        if not self._connected:
            raise OpcUaConnectionError("not connected")
        handler = _StateHandler(on_state, on_command_en)
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

        return StateSubscription(subscription)

    def _state_node(self, service: Service) -> OpcUaNode:
        if service.control is None or "StateCur" not in service.control.nodes:
            raise OpcUaConnectionError(
                f"service {service.name!r} has no StateCur node to read"
            )
        return service.control.nodes["StateCur"]

    def _pea_namespaces(self) -> set[str]:
        """Every distinct namespace URI referenced by the PEA's service nodes."""
        uris: set[str] = set()
        for service in self._pea.services:
            if service.control is None:
                continue
            for opc_node in service.control.nodes.values():
                uris.add(opc_node.namespace)
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

    def __init__(
        self,
        on_state: Callable[[str, ServiceState], None],
        on_command_en: Callable[[str, frozenset[Command]], None] | None,
    ) -> None:
        self._on_state = on_state
        self._on_command_en = on_command_en
        self._routes: dict[str, tuple[str, str]] = {}  # nodeid str -> (service, kind)

    def register(self, nodeid: ua.NodeId, service_name: str, kind: str) -> None:
        self._routes[nodeid.to_string()] = (service_name, kind)

    def datachange_notification(self, node, value, data) -> None:
        route = self._routes.get(node.nodeid.to_string())
        if route is None:
            return
        service_name, kind = route
        if kind == self.STATE:
            try:
                state = decode_state(int(value))
            except UnknownServiceState as exc:
                logger.warning("%s: %s", service_name, exc)
                return
            self._on_state(service_name, state)
        elif kind == self.COMMAND_EN and self._on_command_en is not None:
            self._on_command_en(service_name, decode_command_en(int(value)))
