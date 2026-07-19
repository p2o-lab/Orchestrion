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

from orchestrion.events import EventKind, EventLog
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
    value_meta: dict[str, dict[str, object]]


@dataclass
class _Entry:
    connection: PeaConnection
    pea_id: int
    log: EventLog
    states: dict[str, ServiceState] = field(default_factory=dict)
    command_en: dict[str, frozenset[Command]] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    value_meta: dict[str, dict[str, object]] = field(default_factory=dict)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    subscription: object | None = None
    health_task: asyncio.Task | None = None

    def snapshot(self) -> LiveState:
        return LiveState(
            connected=True,
            states={s: st.name for s, st in self.states.items()},
            command_en={s: [c.name for c in cs] for s, cs in self.command_en.items()},
            values=dict(self.values),
            value_meta={k: dict(v) for k, v in self.value_meta.items()},
        )

    def broadcast(self, message: dict) -> None:
        for queue in self.listeners:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def on_state(self, service: str, state: ServiceState) -> None:
        previous = self.states.get(service)
        self.states[service] = state
        self.broadcast({"kind": "state", "service": service, "state": state.name})
        # [2658-4:2022 Table 14] log an actual transition only. The first callback after
        # subscribe delivers the initial state (previous is None) — an observation, not a
        # transition — so it is not logged; the live panel already shows current state.
        # State names come from state/codes.py (Table-14-verified), never re-spelt here.
        if previous is not None and previous != state:
            self.log.record(
                self.pea_id,
                EventKind.STATE_TRANSITION,
                f"{service}: {previous.name} → {state.name}",
            )

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
        # The event log outlives any single connection: it is the session timeline, so a
        # disconnect/reconnect keeps its history (Step 3 will log both). In-memory only
        # (plan §4) — one store for the app's lifetime, like the registry itself.
        self._log = EventLog()

    def is_connected(self, pea_id: int) -> bool:
        return pea_id in self._entries

    def event_snapshot(self, pea_id: int) -> list[dict[str, object]]:
        """This PEA's recent logged events, oldest first (wire form). Seeds a WS
        viewer (Step 4) and lets tests assert what was recorded."""
        return self._log.snapshot(pea_id)

    def record_event(
        self, pea_id: int, kind: EventKind, message: str, detail: str | None = None
    ) -> None:
        """Record a POL-initiated event — connect/disconnect (here), commands and value
        writes (from `api/control.py`). The single entry point so Step 4 can add WS
        broadcasting to listeners in exactly one place."""
        self._log.record(pea_id, kind, message, detail)

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
        entry = _Entry(connection=connection, pea_id=pea_id, log=self._log)
        entry.value_meta = await connection.read_value_metadata()  # scaling/unit, once
        entry.subscription = await connection.subscribe_service_state(
            entry.on_state,
            on_command_en=entry.on_command_en,
            on_value=entry.on_value,
        )
        entry.health_task = asyncio.create_task(self._health_loop(pea_id))
        self._entries[pea_id] = entry
        # Fresh connection only — the idempotent-reuse path above returns before here, so
        # a re-connect while already live is not logged twice.
        self.record_event(pea_id, EventKind.CONNECTION, "connected", detail=connection.url)
        return entry.snapshot()

    async def disconnect(self, pea_id: int) -> None:
        entry = self._entries.get(pea_id)
        if entry is not None and entry.health_task is not None:
            entry.health_task.cancel()
        if entry is not None:
            self.record_event(pea_id, EventKind.CONNECTION, "disconnected")
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
                    self.record_event(
                        pea_id, EventKind.CONNECTION, "connection to the PEA was lost"
                    )
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
