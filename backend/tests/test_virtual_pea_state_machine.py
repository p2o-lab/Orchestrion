"""VirtualPEA state machine — pinned against [2658-4:2022] Table 14 / §6.2.2."""

from __future__ import annotations

import pytest

from virtual_pea.codes import Command, ServiceState, command_en, enabled_commands
from virtual_pea.state_machine import ServiceStateMachine

S = ServiceState
C = Command


# ── Table 14 codes ─────────────────────────────────────────────────────────────

def test_resetting_is_32768_not_the_mtppy_bug():
    # [Table 14] 2^15. MTPPy and the from-scratch reference both ship 32678.
    assert ServiceState.RESETTING == 32768
    assert ServiceState.RESETTING != 32678


def test_every_state_and_command_is_a_single_bit():
    for value in list(ServiceState) + list(Command):
        assert bin(int(value)).count("1") == 1, value


def test_command_en_round_trips():
    word = command_en(C.START, C.ABORT)
    assert word == C.START | C.ABORT
    assert enabled_commands(word) == {C.START, C.ABORT}


# ── the happy path: IDLE → EXECUTE → COMPLETED → IDLE ───────────────────────────

def test_continuous_run_needs_an_explicit_complete():
    sm = ServiceStateMachine(is_self_completing=False)
    assert sm.state == S.IDLE
    assert sm.allowed_commands() == {C.START}

    assert sm.handle_command(C.START)
    assert sm.state == S.STARTING
    sm.advance()                                  # SC → EXECUTE
    assert sm.state == S.EXECUTE

    # continuous: Execute is stable, Complete is offered
    assert not sm.is_transient()
    assert C.COMPLETE in sm.allowed_commands()

    assert sm.handle_command(C.COMPLETE)
    assert sm.state == S.COMPLETING
    sm.advance()                                  # SC → COMPLETED
    assert sm.state == S.COMPLETED

    assert sm.handle_command(C.RESET)
    sm.advance()                                  # SC → IDLE
    assert sm.state == S.IDLE


def test_self_completing_execute_is_transient_and_offers_no_complete():
    sm = ServiceStateMachine(is_self_completing=True)
    sm.handle_command(C.START)
    sm.advance()                                  # → EXECUTE
    assert sm.state == S.EXECUTE
    # [§6.2.2.1] self-completing Execute is transient; Complete is meaningless.
    assert sm.is_transient()
    assert C.COMPLETE not in sm.allowed_commands()
    sm.advance()                                  # SC → COMPLETING
    assert sm.state == S.COMPLETING


# ── the level model (§6.2.2.1) ──────────────────────────────────────────────────

def test_abort_from_any_lower_level():
    for start in (S.EXECUTE, S.STARTING, S.HELD, S.STOPPED, S.PAUSED):
        sm = ServiceStateMachine(is_self_completing=False)
        sm.state = start
        assert C.ABORT in sm.allowed_commands(), start
        assert sm.handle_command(C.ABORT)
        assert sm.state == S.ABORTING


def test_stop_available_below_level_4_but_not_at_or_above():
    below = ServiceStateMachine(is_self_completing=False)
    below.state = S.EXECUTE
    assert C.STOP in below.allowed_commands()

    at = ServiceStateMachine(is_self_completing=False)
    at.state = S.STOPPED                          # level 4 — Stop no longer applies
    assert C.STOP not in at.allowed_commands()


def test_hold_only_below_level_3():
    sm = ServiceStateMachine(is_self_completing=False)
    sm.state = S.EXECUTE
    assert C.HOLD in sm.allowed_commands()
    sm.state = S.HELD                             # level 3
    assert C.HOLD not in sm.allowed_commands()


def test_idle_offers_only_start():
    sm = ServiceStateMachine(is_self_completing=False)
    # [§6.2.2.1] Idle is level 5 — no Abort/Stop/Hold from a settled Idle.
    assert sm.allowed_commands() == {C.START}


# ── rejection ───────────────────────────────────────────────────────────────────

def test_disallowed_command_is_dropped_not_raised():
    sm = ServiceStateMachine(is_self_completing=False)
    # [§6.2.2.4] a command without its CommandEn bit is not executed.
    assert sm.handle_command(C.STOP) is False
    assert sm.state == S.IDLE


def test_restart_from_execute_goes_to_starting():
    sm = ServiceStateMachine(is_self_completing=False)
    sm.state = S.EXECUTE
    assert sm.handle_command(C.RESTART)
    assert sm.state == S.STARTING


def test_stable_state_advance_is_a_noop():
    sm = ServiceStateMachine(is_self_completing=False)
    assert sm.advance() is False                  # IDLE is stable
    assert sm.state == S.IDLE
