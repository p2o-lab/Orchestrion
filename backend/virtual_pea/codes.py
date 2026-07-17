"""The service control/status word encoding — [2658-4:2022] Table 14.

Verified line by line against the PDF, not copied from any peer. In particular
RESETTING is **32768 (2^15)**; MTPPy ships 32678, a digit-transposition bug, and
the from-scratch reference copied it forward. Every value here is a power of two:
StateCur, Command and CommandEn are 32-bit words with exactly one bit set (Table
14; §6.2.2.3 makes the encoding mandatory).

This module has no OPC UA and no POL dependency: the VirtualPEA encodes states
from here, and the POL decodes them from its own copy of Table 14, independently.
"""

from __future__ import annotations

from enum import IntEnum


class ServiceState(IntEnum):
    """`StateCur` values — [2658-4:2022] Table 14 (state column).

    Transient states (all "-ing", plus Execute for a self-completing procedure)
    advance automatically to a successor; the rest are stable. See state_machine.
    """

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
    RESETTING = 32768  # [Table 14] 2^15 — NOT MTPPy's 32678
    COMPLETING = 65536
    COMPLETED = 131072


class Command(IntEnum):
    """`CommandOp`/`CommandInt`/`CommandExt` values — [2658-4:2022] Table 14.

    The POL writes one of these; the PEA acts on it only if the corresponding
    CommandEn bit is set (§6.2.2.4) and clears the command word back to 0 after
    interpreting it (§8.2.2.3).
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


# [2658-4:2022] Table 14 (CommandEn column). Bit N of CommandEn enables the
# command whose integer value is 2^N — i.e. the command's own code IS its enable
# bit, because commands are single-bit powers of two. So CommandEn is simply the
# bitwise OR of every currently-acceptable Command. The PEA owns write access;
# the POL reads it to know which transitions are legal right now (§6.2.2.4).
def command_en(*commands: Command) -> int:
    """OR the given commands into a CommandEn word."""
    word = 0
    for command in commands:
        word |= int(command)
    return word


def enabled_commands(command_en_word: int) -> frozenset[Command]:
    """The commands a CommandEn word enables — the inverse of command_en()."""
    return frozenset(c for c in Command if command_en_word & int(c))
