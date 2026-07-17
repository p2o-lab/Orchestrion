"""Decode a service's control/status words — [2658-4:2022] Table 14.

`StateCur`, the `Command*` words and `CommandEn` are 32-bit words in which each
meaning is a single set bit (Table 14; §6.2.2.3 makes the encoding mandatory).
`StateCur` and each `Command*` carry exactly one bit; `CommandEn` ORs together every
command the PEA currently allows (§6.2.2.4).

"""

from __future__ import annotations

from enum import IntEnum


class ServiceState(IntEnum):
    """A `StateCur` value — [2658-4:2022] Table 14."""

    STOPPED = 4
    STARTING = 8
    IDLE = 16
    PAUSED = 32
    EXECUTE = 64
    STOPPING = 128
    ABORTING = 256
    ABORTED = 512
    HOLDING = 1024
    HELD = 2048
    UNHOLDING = 4096
    PAUSING = 8192
    RESUMING = 16384
    RESETTING = 32768
    COMPLETING = 65536
    COMPLETED = 131072


class Command(IntEnum):
    """A `CommandOp`/`CommandInt`/`CommandExt` value — [2658-4:2022] Table 14.

    The POL writes one of these (M3); the PEA acts on it only if the matching
    CommandEn bit is set, then clears the command word to 0 (§8.2.2.3).
    """

    RESET = 2
    START = 4
    STOP = 8
    HOLD = 16
    UNHOLD = 32
    PAUSE = 64
    RESUME = 128
    ABORT = 256
    RESTART = 512
    COMPLETE = 1024


class UnknownServiceState(ValueError):
    """A `StateCur` value that is not defined in [2658-4:2022] Table 14.

    Raised rather than swallowed: a conformant PEA only ever publishes a Table 14
    state, so an unknown value is a real anomaly the POL must surface, not hide.
    """

    def __init__(self, value: int) -> None:
        self.value = value
        super().__init__(
            f"StateCur={value} is not a [2658-4:2022] Table 14 state "
            f"(known: {[int(s) for s in ServiceState]})"
        )


def decode_state(value: int) -> ServiceState:
    """Turn a raw `StateCur` word into a `ServiceState`.

    Raises `UnknownServiceState` if the value is not in Table 14.
    """
    try:
        return ServiceState(value)
    except ValueError:
        raise UnknownServiceState(value) from None


def decode_command_en(value: int) -> frozenset[Command]:
    """The commands a `CommandEn` word currently enables — [2658-4:2022] §6.2.2.4.

    Bit N of CommandEn enables the command whose value is 2^N; since every Command is
    a single-bit power of two, that is just the commands whose bit is set. Bits that
    match no defined command are ignored (they are reserved — Table 14 marks 0, 1 and
    11..31 as unused).
    """
    return frozenset(c for c in Command if value & int(c))
