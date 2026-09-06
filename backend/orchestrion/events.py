"""The event log — a chronological, in-memory record of meaningful discrete events.

M4 (plan §2 item 6): "Log everything (mode/procedure changes, state transitions,
commands, operator actions), visible in the UI." This module is the **store** only —
a pure `Event` value + a bounded per-PEA buffer, with no FastAPI and no OPC UA above
it (the same domain-only boundary `state/codes.py` keeps). The registry feeds it
(Step 2), the API layer feeds it (Step 3), and `api/live.py` streams it over the
existing per-PEA WebSocket (Step 4).

Scope (plan §4): **in-memory + streamed only.** No database historian, no GMP audit
trail — that stays v2. Events survive only for the app's lifetime.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# Per-PEA ring buffer size. Bounded so a long-running session cannot grow without
# limit; the oldest events fall off once this many are held.
MAX_EVENTS_PER_PEA = 500


class EventKind(str, Enum):
    """What a logged event is. `str`-valued so it serialises straight to JSON.

    The set mirrors the event types plan §2 item 6 names; each concrete kind is one
    the registry (Step 2) or the API layer (Step 3) actually emits. Standard concepts
    referenced in an event's `message` (service states, commands) are named via
    `state/codes.py`, which is verified against [2658-4:2022] Table 14 — never re-spelt
    from memory here.
    """

    STATE_TRANSITION = "state_transition"
    """A service's `StateCur` changed — [2658-4:2022] Table 14 (from the PEA)."""

    COMMAND = "command"
    """The POL issued a command / Start — [2658-4:2022] §8.2.2.3 (POL→PEA)."""

    MODE = "mode"
    """The POL took the service to Automatic + External — [2658-4:2022] §6.2.1 (POL→PEA).
    Logged only when the mode/source actually transitioned, not on the idempotent
    re-assertion before every command."""

    CONNECTION = "connection"
    """An operator connect/disconnect, or the registry dropping a dead PEA."""

    VALUE_WRITE = "value_write"
    """The operator wrote an incoming process value — [2658-4:2022] §6.3.3."""


@dataclass(frozen=True)
class Event:
    """One logged event. Immutable: a record of something that already happened."""

    timestamp: datetime
    """When it was recorded — timezone-aware UTC."""

    pea_id: int
    kind: EventKind
    message: str
    """A short human-readable line, e.g. ``Stirring: IDLE → EXECUTE``."""

    detail: str | None = None
    """Optional extra context (e.g. an error message on a failed command)."""

    def to_dict(self) -> dict[str, object]:
        """The wire form for the WebSocket. `pea_id` is omitted — the stream is
        already per-PEA (`/api/peas/{id}/ws`), so it would be redundant, exactly as
        the state/value messages omit it."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "kind": self.kind.value,
            "message": self.message,
            "detail": self.detail,
        }


class EventLog:
    """A bounded, per-PEA, in-memory event buffer.

    One instance is owned for the app's lifetime (wired in Step 2), the same way the
    `PeaRegistry` is. Every meaningful event is `record`ed here; a newly-opened WS
    viewer is seeded from `snapshot`, and each new event is broadcast live.
    """

    def __init__(self, max_per_pea: int = MAX_EVENTS_PER_PEA) -> None:
        self._max = max_per_pea
        # defaultdict so the first event for a PEA creates its buffer; maxlen makes the
        # deque evict the oldest event automatically once full.
        self._events: dict[int, deque[Event]] = defaultdict(
            lambda: deque(maxlen=self._max)
        )

    def record(
        self, pea_id: int, kind: EventKind, message: str, detail: str | None = None
    ) -> Event:
        """Append a new event (stamped now, UTC) and return it.

        Returns the `Event` so a caller can both store and broadcast it in one step —
        e.g. the registry appends, then pushes `event.to_dict()` to its WS listeners.
        """
        event = Event(
            timestamp=datetime.now(timezone.utc),
            pea_id=pea_id,
            kind=kind,
            message=message,
            detail=detail,
        )
        self._events[pea_id].append(event)
        return event

    def events(self, pea_id: int) -> list[Event]:
        """This PEA's events, oldest first. Empty if none have been recorded."""
        return list(self._events.get(pea_id, ()))

    def snapshot(self, pea_id: int) -> list[dict[str, object]]:
        """The wire form of `events(pea_id)` — seeds a newly-opened WS viewer."""
        return [event.to_dict() for event in self.events(pea_id)]

    def clear(self, pea_id: int) -> None:
        """Drop a PEA's events — used when its connection is torn down."""
        self._events.pop(pea_id, None)
