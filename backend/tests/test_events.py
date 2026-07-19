"""The in-memory event log store — M4 Step 1 (orchestrion/events.py)."""

from __future__ import annotations

from datetime import datetime, timezone

from orchestrion.events import Event, EventKind, EventLog


def test_record_returns_and_stores_the_event():
    log = EventLog()
    event = log.record(1, EventKind.STATE_TRANSITION, "Stirring: IDLE → EXECUTE")
    assert isinstance(event, Event)
    assert event.pea_id == 1
    assert event.kind is EventKind.STATE_TRANSITION
    assert event.message == "Stirring: IDLE → EXECUTE"
    assert event.detail is None
    # the returned event is the one stored
    assert log.events(1) == [event]


def test_timestamp_is_timezone_aware_utc():
    log = EventLog()
    event = log.record(1, EventKind.CONNECTION, "connected")
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timezone.utc.utcoffset(datetime.now(timezone.utc))


def test_events_are_kept_in_chronological_order():
    log = EventLog()
    log.record(1, EventKind.CONNECTION, "connected")
    log.record(1, EventKind.COMMAND, "Start Continous")
    log.record(1, EventKind.STATE_TRANSITION, "Stirring: IDLE → STARTING")
    assert [e.message for e in log.events(1)] == [
        "connected",
        "Start Continous",
        "Stirring: IDLE → STARTING",
    ]


def test_events_are_isolated_per_pea():
    log = EventLog()
    log.record(1, EventKind.CONNECTION, "pea one")
    log.record(2, EventKind.CONNECTION, "pea two")
    assert [e.message for e in log.events(1)] == ["pea one"]
    assert [e.message for e in log.events(2)] == ["pea two"]


def test_unknown_pea_has_no_events():
    log = EventLog()
    assert log.events(999) == []
    assert log.snapshot(999) == []


def test_buffer_is_bounded_and_evicts_oldest_first():
    log = EventLog(max_per_pea=3)
    for i in range(5):
        log.record(1, EventKind.STATE_TRANSITION, f"event {i}")
    # only the last 3 survive; events 0 and 1 were evicted
    assert [e.message for e in log.events(1)] == ["event 2", "event 3", "event 4"]


def test_reading_events_does_not_expose_the_internal_buffer():
    log = EventLog()
    log.record(1, EventKind.CONNECTION, "connected")
    got = log.events(1)
    got.clear()  # mutating the returned list must not touch the store
    assert len(log.events(1)) == 1


def test_snapshot_is_the_wire_form_oldest_first():
    log = EventLog()
    log.record(1, EventKind.CONNECTION, "connected")
    log.record(1, EventKind.VALUE_WRITE, "HC30_Target_Full := true", detail="§6.3.3")
    snap = log.snapshot(1)
    assert [row["message"] for row in snap] == [
        "connected",
        "HC30_Target_Full := true",
    ]
    row = snap[1]
    assert row["kind"] == "value_write"
    assert row["detail"] == "§6.3.3"
    assert "pea_id" not in row  # per-PEA stream — omitted, like state/value messages
    # timestamp round-trips as an ISO 8601 string
    assert datetime.fromisoformat(str(row["timestamp"])).tzinfo is not None


def test_clear_drops_a_peas_events():
    log = EventLog()
    log.record(1, EventKind.CONNECTION, "connected")
    log.clear(1)
    assert log.events(1) == []
