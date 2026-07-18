"""Persistent live PEA connections — started/stopped by explicit connect/disconnect.

A connection lives here for as long as it is *intended* to (until the user disconnects
or the PEA dies), independent of any WebSocket viewer — so navigating away and back
finds it still connected. A per-entry background task pings the server on an interval;
if the PEA has gone away the entry is dropped and its viewers are told, so the status
is always the real one (this is what the earlier, buggy shared connection got wrong).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from orchestrion.mtp.model import Pea
from orchestrion.opcua.connection import PeaConnection
from orchestrion.state.codes import Command, ServiceState

_HEALTH_INTERVAL = 2.0


@dataclass
class LiveState:
    connected: bool
    states: dict[str, str]
    command_en: dict[str, list[str]]
    values: dict[str, object]


@dataclass
class _Entry:
    connection: PeaConnection
    states: dict[str, ServiceState] = field(default_factory=dict)
    command_en: dict[str, frozenset[Command]] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    subscription: object | None = None
    health_task: asyncio.Task | None = None

    def snapshot(self) -> LiveState:
        return LiveState(
            connected=True,
            states={s: st.name for s, st in self.states.items()},
            command_en={s: [c.name for c in cs] for s, cs in self.command_en.items()},
            values=dict(self.values),
        )

    def broadcast(self, message: dict) -> None:
        for queue in self.listeners:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def on_state(self, service: str, state: ServiceState) -> None:
        self.states[service] = state
        self.broadcast({"kind": "state", "service": service, "state": state.name})

    def on_command_en(self, service: str, commands: frozenset[Command]) -> None:
        self.command_en[service] = commands
        self.broadcast(
            {"kind": "command_en", "service": service,
             "command_en": [c.name for c in commands]}
        )

    def on_value(self, name: str, value: object) -> None:
        self.values[name] = value
        self.broadcast({"kind": "value", "name": name, "value": value})


class PeaRegistry:
    """Persistent OPC UA connections keyed by DB pea_id."""

    def __init__(self) -> None:
        self._entries: dict[int, _Entry] = {}

    def is_connected(self, pea_id: int) -> bool:
        return pea_id in self._entries

    def snapshot(self, pea_id: int) -> LiveState | None:
        entry = self._entries.get(pea_id)
        return entry.snapshot() if entry is not None else None

    def connection(self, pea_id: int) -> PeaConnection | None:
        """The live connection for a connected PEA, or None if not connected."""
        entry = self._entries.get(pea_id)
        return entry.connection if entry is not None else None

    async def connect(self, pea_id: int, pea: Pea) -> LiveState:
        """Establish (or reuse a live) persistent connection. Raises if unreachable."""
        entry = self._entries.get(pea_id)
        if entry is not None:
            if await entry.connection.is_alive():
                return entry.snapshot()
            await self._drop(pea_id)  # stale/dead -> replace with a fresh one

        connection = PeaConnection(pea)
        await connection.connect()  # OpcUaConnectionError if the PEA is unreachable
        entry = _Entry(connection=connection)
        entry.subscription = await connection.subscribe_service_state(
            entry.on_state,
            on_command_en=entry.on_command_en,
            on_value=entry.on_value,
        )
        entry.health_task = asyncio.create_task(self._health_loop(pea_id))
        self._entries[pea_id] = entry
        return entry.snapshot()

    async def disconnect(self, pea_id: int) -> None:
        entry = self._entries.get(pea_id)
        if entry is not None and entry.health_task is not None:
            entry.health_task.cancel()
        await self._drop(pea_id)

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

    # ── internals ────────────────────────────────────────────────────────────

    async def _health_loop(self, pea_id: int) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                await asyncio.sleep(_HEALTH_INTERVAL)
                entry = self._entries.get(pea_id)
                if entry is None:
                    return
                if not await entry.connection.is_alive():
                    entry.broadcast({"kind": "closed", "detail": "connection to the PEA was lost"})
                    self._entries.pop(pea_id, None)
                    await self._teardown(entry)  # not disconnect(): don't cancel self
                    return

    async def _drop(self, pea_id: int) -> None:
        entry = self._entries.pop(pea_id, None)
        if entry is not None:
            await self._teardown(entry)

    @staticmethod
    async def _teardown(entry: _Entry) -> None:
        if entry.subscription is not None:
            with contextlib.suppress(Exception):
                await entry.subscription.delete()
        await entry.connection.disconnect()
