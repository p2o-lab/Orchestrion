"""Runtime registry of live PEA connections — the bridge from OPC UA to the UI.

Persistence (`orchestrion.db`) holds the *static* PEA (its MTP). This holds the
*live* one: an open `PeaConnection`, the latest decoded state per service, and the set
of listeners (WebSockets) to push changes to. Keyed by the DB `pea_id`, it lives for
the app's lifetime on the single asyncio loop that also runs the OPC UA subscriptions.

The subscription callback is synchronous (asyncua calls it); it updates the snapshot
and fans out to each listener's `asyncio.Queue` via `put_nowait` — which is safe to
call from that context — so no await happens inside the callback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from orchestrion.mtp.model import Pea
from orchestrion.opcua.connection import PeaConnection
from orchestrion.state.codes import Command, ServiceState


@dataclass
class LiveState:
    """A serialisable snapshot of one PEA's live service states."""

    connected: bool
    states: dict[str, str]                 # service name -> ServiceState.name
    command_en: dict[str, list[str]]       # service name -> enabled Command names


@dataclass
class _Entry:
    connection: PeaConnection
    states: dict[str, ServiceState] = field(default_factory=dict)
    command_en: dict[str, frozenset[Command]] = field(default_factory=dict)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    subscription: object | None = None

    def snapshot(self) -> LiveState:
        return LiveState(
            connected=True,
            states={s: st.name for s, st in self.states.items()},
            command_en={s: [c.name for c in cs] for s, cs in self.command_en.items()},
        )

    def _broadcast(self, message: dict) -> None:
        for queue in self.listeners:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass          # a slow listener drops updates rather than blocking

    def on_state(self, service_name: str, state: ServiceState) -> None:
        self.states[service_name] = state
        self._broadcast({"service": service_name, "state": state.name})

    def on_command_en(self, service_name: str, commands: frozenset[Command]) -> None:
        self.command_en[service_name] = commands
        self._broadcast(
            {"service": service_name, "command_en": [c.name for c in commands]}
        )


class PeaRegistry:
    """Manages live connections for imported PEAs, keyed by DB pea_id."""

    def __init__(self) -> None:
        self._entries: dict[int, _Entry] = {}

    def is_connected(self, pea_id: int) -> bool:
        return pea_id in self._entries

    async def connect(self, pea_id: int, pea: Pea) -> LiveState:
        """Open a session to `pea` (idempotent) and subscribe to its live state."""
        if pea_id in self._entries:
            return self._entries[pea_id].snapshot()

        connection = PeaConnection(pea)
        await connection.connect()
        entry = _Entry(connection=connection)
        # subscribe_service_state delivers the initial value of each node, so the
        # snapshot is populated before this returns.
        entry.subscription = await connection.subscribe_service_state(
            entry.on_state, on_command_en=entry.on_command_en
        )
        self._entries[pea_id] = entry
        return entry.snapshot()

    async def disconnect(self, pea_id: int) -> None:
        entry = self._entries.pop(pea_id, None)
        if entry is None:
            return
        if entry.subscription is not None:
            await entry.subscription.delete()
        await entry.connection.disconnect()

    def snapshot(self, pea_id: int) -> LiveState | None:
        entry = self._entries.get(pea_id)
        return entry.snapshot() if entry is not None else None

    def add_listener(self, pea_id: int, queue: asyncio.Queue) -> None:
        entry = self._entries.get(pea_id)
        if entry is not None:
            entry.listeners.add(queue)

    def remove_listener(self, pea_id: int, queue: asyncio.Queue) -> None:
        entry = self._entries.get(pea_id)
        if entry is not None:
            entry.listeners.discard(queue)

    async def shutdown(self) -> None:
        for pea_id in list(self._entries):
            await self.disconnect(pea_id)
