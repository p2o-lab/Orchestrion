"""Classify a service state as acting or waiting — [IEC 61512-1] items 2382-2390.

`codes.py` decodes the wire ([2658-4:2022] Table 14); this module says what a decoded
state *means* to a recipe. That is an **ISA-88** concept, not a Table 14 one, which is
why it lives in its own file with its own citation.

[IEC 61512-1] items 2381-2390 define exactly two kinds of procedural state:

    "A state (name ending in "ING") in which the procedural element may orchestrate a
     defined set of actions... Transition from an acting state occurs either upon
     completion of its defined task or upon receipt of a suitable command."

    "A state for which the procedural element has previously achieved a defined set of
     conditions and is not permitted to direct any immediate actions... Transition from
     a waiting state occurs only upon receipt of a suitable command."

The waiting states are then split by what the engine must *do* about them, which is our
design (`POL_Step_Model_ISA88.md` §6), grounded in:
  - items 2391-2393  — the terms Initial State and Final State;
  - items 3444-3451  — one execution runs from IDLE until "a final waiting state that
    indicates either normal completion (COMPLETE) or abnormal termination (STOPPED or
    ABORTED)", whereupon the parent "may progress its own operating sequence";
  - items 2341-2369  — PAUSE and HOLD are the two *recoverable* exception levels; STOP
    and ABORT are not.

⚠ MTP's 16 states are NOT the ISA-88 Reference Procedural State Model state for state:
MTP drops SUSPENDING/SUSPENDED/UNSUSPENDING/CLEARING, adds RESUMING, and renames
RUNNING -> EXECUTE and COMPLETE -> COMPLETED. The *test* above is what we borrow, and it
is applied here to MTP's own 16 states. (`POL_Step_Model_ISA88.md` §1.)

"""

from __future__ import annotations

from enum import Enum

from orchestrion.state.codes import ServiceState


class StateClass(Enum):
    """What a `ServiceState` means to a running recipe step."""

    ACTING = "acting"
    """The PEA is working. Keep waiting — [61512-1] item 2382."""

    INITIAL = "initial"
    """Waiting, ready to be started — [61512-1] items 2391-2393 "Initial State"."""

    INTERRUPTED = "interrupted"
    """Waiting on an *operator* command after a recoverable exception (PAUSE/HOLD —
    [61512-1] items 2341-2352). The run reports held/paused and waits; it does not fail."""

    TERMINAL_NORMAL = "terminal_normal"
    """A Final State reached by normal completion — [61512-1] item 3447. Latch, then RESET."""

    TERMINAL_ABNORMAL = "terminal_abnormal"
    """A Final State reached by abnormal termination (STOP/ABORT — items 2355-2369).
    The run fails."""


# The mapping is written out in full, one row per state, deliberately: there is NO
# default arm and no `_ = ACTING` fallback. Adding a state to `ServiceState` without
# classifying it must fail loudly (see `_check_exhaustive` below) rather than silently
# becoming "keep waiting" — `POL_Step_Model_ISA88.md` §6.
_CLASS: dict[ServiceState, StateClass] = {
    # --- acting: name ends in "ING" [item 2382] ------------------------------------
    ServiceState.STARTING: StateClass.ACTING,
    ServiceState.COMPLETING: StateClass.ACTING,
    ServiceState.RESETTING: StateClass.ACTING,
    ServiceState.HOLDING: StateClass.ACTING,
    ServiceState.UNHOLDING: StateClass.ACTING,
    ServiceState.PAUSING: StateClass.ACTING,
    ServiceState.RESUMING: StateClass.ACTING,
    ServiceState.STOPPING: StateClass.ACTING,
    ServiceState.ABORTING: StateClass.ACTING,
    # EXECUTE is acting although its name does not end in "ING": 2658-4 renamed
    # ISA-88's RUNNING, whose Table B.2 row reads "Directs normal sequencing of the
    # process-oriented task... Upon completion, control passes to COMPLETING."
    # [DERIVED] — item 2382's literal test is the name; the substance is unambiguous.
    ServiceState.EXECUTE: StateClass.ACTING,
    # --- waiting [item 2387] --------------------------------------------------------
    ServiceState.IDLE: StateClass.INITIAL,
    ServiceState.HELD: StateClass.INTERRUPTED,
    ServiceState.PAUSED: StateClass.INTERRUPTED,
    ServiceState.COMPLETED: StateClass.TERMINAL_NORMAL,
    ServiceState.STOPPED: StateClass.TERMINAL_ABNORMAL,
    ServiceState.ABORTED: StateClass.TERMINAL_ABNORMAL,
}


def _check_exhaustive() -> None:
    """Fail at import if a `ServiceState` is unclassified.

    This is the whole point of having no default arm: a future Table 14 addition
    becomes an import-time error here, not a step that silently hangs "acting".
    """
    missing = sorted(s.name for s in ServiceState if s not in _CLASS)
    if missing:
        raise RuntimeError(
            f"orchestrion.state.classification: unclassified ServiceState(s): "
            f"{missing}. Add each to _CLASS — do not add a default."
        )


_check_exhaustive()


def classify(state: ServiceState) -> StateClass:
    """The `StateClass` of a decoded service state.

    Raises `KeyError` for anything that is not a `ServiceState`; callers decode with
    `codes.decode_state`, which already raises `UnknownServiceState` off-Table-14.
    """
    return _CLASS[state]


def is_acting(state: ServiceState) -> bool:
    """The PEA is working — keep waiting. [61512-1] item 2382."""
    return classify(state) is StateClass.ACTING


def is_waiting(state: ServiceState) -> bool:
    """The PEA has stopped and needs a command to move. [61512-1] item 2387."""
    return not is_acting(state)


def is_final(state: ServiceState) -> bool:
    """A Final State — normal completion or abnormal termination.

    This is gate #1 of `POL_Step_Model_ISA88.md` §3: [61512-1] item 3450, "Upon this
    procedural element reaching a final state, the higher level procedural element...
    may progress its own operating sequence to the next step."

    ⚠ IDLE is *not* final — item 2391 calls it the **Initial** State.
    """
    return classify(state) in (StateClass.TERMINAL_NORMAL, StateClass.TERMINAL_ABNORMAL)
