"""The service state machine — [2658-4:2022] §6.2.2, verified from the PDF.

16 states in 5 priority levels (§6.2.2.1). Three kinds of transition:

* **command** — the POL requests one via a Command word; honoured only if its
  CommandEn bit is set.
* **level jump** — §6.2.2.1: *"a change from a lower level to a higher level can
  take place at any time"*. Complete→L2, Hold→L3, Stop→L4, Abort→L5. This is why
  Stop/Abort work from almost anywhere, and it is computed from the level table
  rather than enumerated edge by edge.
* **SC (state change)** — §6.2.2.1: transient states advance to their successor
  on their own once their function is done. Execute is transient **only for a
  self-completing procedure** (§6.2.2.1, §6.2.3.2); for a continuous procedure it
  is stable and leaves only via the Complete command.

No OPC UA here — this is pure logic the server layer drives.
"""

from __future__ import annotations

from collections.abc import Callable

from virtual_pea.codes import Command, ServiceState, command_en

S = ServiceState
C = Command

# [2658-4:2022 §6.2.2.1] the level of each state. Higher = higher priority; a jump
# to a higher level may happen at any time. Levels are cumulative in the text
# ("... as well as level N"); this table gives each state its own level.
LEVEL: dict[ServiceState, int] = {
    S.EXECUTE: 1, S.PAUSING: 1, S.PAUSED: 1, S.RESUMING: 1,
    S.STARTING: 2, S.COMPLETING: 2, S.UNHOLDING: 2,
    S.HOLDING: 3, S.HELD: 3,
    S.STOPPING: 4, S.STOPPED: 4,
    S.IDLE: 5, S.COMPLETED: 5, S.RESETTING: 5, S.ABORTING: 5, S.ABORTED: 5,
}

# [§6.2.2.1] the command that carries a service up to each level, and the transient
# state that jump lands in. Complete is special-cased (Execute + continuous only).
_LEVEL_JUMP: dict[Command, tuple[int, ServiceState]] = {
    C.HOLD: (3, S.HOLDING),
    C.STOP: (4, S.STOPPING),
    C.ABORT: (5, S.ABORTING),
}

# Command edges that are NOT level jumps — the ordinary progression within/toward
# a level. Verified: Start Idle→Starting and Restart Execute→Starting (§8.2.2.5,
# PDF line "via Start, and from Execute to Starting, via Restart"); Pause/Resume/
# Unhold/Reset from Figure 3 and the level semantics.
_COMMAND_EDGES: dict[tuple[ServiceState, Command], ServiceState] = {
    (S.IDLE, C.START): S.STARTING,
    (S.EXECUTE, C.RESTART): S.STARTING,
    (S.EXECUTE, C.PAUSE): S.PAUSING,
    (S.PAUSED, C.RESUME): S.RESUMING,
    (S.HELD, C.UNHOLD): S.UNHOLDING,
    (S.COMPLETED, C.RESET): S.RESETTING,
    (S.STOPPED, C.RESET): S.RESETTING,
    (S.ABORTED, C.RESET): S.RESETTING,
}

# [§6.2.2.1] "SC" transitions: each transient state auto-advances here once done.
# Execute is deliberately absent — its SC target depends on the procedure kind and
# is handled in next_sc().
_SC: dict[ServiceState, ServiceState] = {
    S.STARTING: S.EXECUTE,
    S.COMPLETING: S.COMPLETED,
    S.PAUSING: S.PAUSED,
    S.RESUMING: S.EXECUTE,
    S.HOLDING: S.HELD,
    S.UNHOLDING: S.EXECUTE,
    S.STOPPING: S.STOPPED,
    S.ABORTING: S.ABORTED,
    S.RESETTING: S.IDLE,
}


class ServiceStateMachine:
    """One service's lifecycle. Starts in IDLE ([§6.2.2.1], the initial state)."""

    def __init__(
        self,
        *,
        is_self_completing: bool,
        on_change: Callable[[ServiceState], None] | None = None,
    ) -> None:
        self.state: ServiceState = S.IDLE
        self._is_self_completing = is_self_completing
        self._on_change = on_change

    def set_self_completing(self, value: bool) -> None:
        """The active procedure's kind decides whether Execute self-terminates."""
        self._is_self_completing = value

    # ── queries ──────────────────────────────────────────────────────────────

    def allowed_commands(self) -> frozenset[Command]:
        """Commands acceptable from the current state — the CommandEn contents.

        Note: this is the *nominal* set from the state machine. A real PEA may
        additionally interlock a transition on process conditions (§6.2.2.4); the
        VirtualPEA has no process interlocks, so nominal == actual here.
        """
        current = self.state
        allowed: set[Command] = set()

        # ordinary command edges out of this state
        allowed.update(cmd for (st, cmd) in _COMMAND_EDGES if st == current)

        # level jumps: available from any state below the target level
        for cmd, (target_level, _) in _LEVEL_JUMP.items():
            if LEVEL[current] < target_level:
                allowed.add(cmd)

        # Complete: [§6.2.2.1 + §6.2.3.2] only from Execute, only for a continuous
        # (i.e. non-self-completing) procedure. A self-completing one leaves
        # Execute by SC, so Complete would be meaningless.
        if current == S.EXECUTE and not self._is_self_completing:
            allowed.add(C.COMPLETE)

        return frozenset(allowed)

    def command_en_word(self) -> int:
        """CommandEn as a 32-bit word — [2658-4:2022] Table 14."""
        return command_en(*self.allowed_commands())

    def is_transient(self) -> bool:
        """Whether the current state auto-advances (has an SC successor)."""
        return self.next_sc() is not None

    def next_sc(self) -> ServiceState | None:
        """The SC successor of the current state, or None if it is stable."""
        if self.state in _SC:
            return _SC[self.state]
        # [§6.2.2.1] Execute is transient iff the procedure is self-completing.
        if self.state == S.EXECUTE and self._is_self_completing:
            return S.COMPLETING
        return None

    # ── transitions ──────────────────────────────────────────────────────────

    def handle_command(self, command: Command) -> bool:
        """Apply a POL command. Returns True if it was accepted.

        [§6.2.2.4] a command whose CommandEn bit is not set is not executed — the
        PEA silently drops it. We mirror that: reject, do not raise.
        """
        if command not in self.allowed_commands():
            return False

        if command in _LEVEL_JUMP:
            _, target_state = _LEVEL_JUMP[command]
            self._go(target_state)
        elif command == C.COMPLETE:
            self._go(S.COMPLETING)
        else:
            self._go(_COMMAND_EDGES[(self.state, command)])
        return True

    def advance(self) -> bool:
        """Perform the pending SC transition, if the current state is transient.

        The server calls this after a transient state's work is done (immediately,
        for the VirtualPEA — there is no real equipment to wait on).
        """
        successor = self.next_sc()
        if successor is None:
            return False
        self._go(successor)
        return True

    def _go(self, new_state: ServiceState) -> None:
        if new_state == self.state:
            return
        self.state = new_state
        if self._on_change is not None:
            self._on_change(new_state)
