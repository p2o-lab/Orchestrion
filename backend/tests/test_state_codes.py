"""POL state decode — pinned against [2658-4:2022] Table 14."""

from __future__ import annotations

import pytest

from orchestrion.state.codes import (
    Command,
    ServiceState,
    UnknownServiceState,
    decode_command_en,
    decode_state,
)


def test_table_14_state_values():
    # [Table 14] the exact integers a PEA publishes on StateCur.
    assert ServiceState.IDLE == 16
    assert ServiceState.EXECUTE == 64
    assert ServiceState.COMPLETED == 131072
    assert ServiceState.RESETTING == 32768          # 2^15, not MTPPy's 32678


def test_table_14_command_values():
    assert Command.RESET == 2
    assert Command.START == 4
    assert Command.COMPLETE == 1024


def test_all_codes_are_single_bit():
    for value in list(ServiceState) + list(Command):
        assert bin(int(value)).count("1") == 1, value


def test_decode_state_round_trips_every_state():
    for state in ServiceState:
        assert decode_state(int(state)) is state


def test_decode_state_raises_on_unknown():
    # A value no Table 14 state uses (0 is "not used").
    with pytest.raises(UnknownServiceState):
        decode_state(0)
    with pytest.raises(UnknownServiceState):
        decode_state(63)


def test_decode_command_en_extracts_allowed_commands():
    # e.g. the enable word a service offers from IDLE (only Start).
    assert decode_command_en(int(Command.START)) == {Command.START}
    # EXECUTE (continuous): several commands OR'd together.
    word = Command.STOP | Command.PAUSE | Command.HOLD | Command.ABORT | Command.COMPLETE
    assert decode_command_en(word) == {
        Command.STOP, Command.PAUSE, Command.HOLD, Command.ABORT, Command.COMPLETE
    }


def test_decode_command_en_ignores_reserved_bits():
    # [Table 14] bits 0, 1, 11..31 are reserved/unused — must not decode to a command.
    assert decode_command_en(1) == frozenset()          # bit 0
    assert decode_command_en(int(Command.START) | (1 << 20)) == {Command.START}
