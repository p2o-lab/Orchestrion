"""Acting/waiting classification — pinned against [IEC 61512-1] items 2382-2390.

The point of this module is exhaustiveness: every Table 14 state must be classified,
with no default arm, so a future addition fails loudly instead of silently becoming
"keep waiting" (`POL_Step_Model_ISA88.md` §6).
"""

from __future__ import annotations

import pytest

from orchestrion.state.classification import (
    StateClass,
    classify,
    is_acting,
    is_final,
    is_waiting,
)
from orchestrion.state.codes import ServiceState

# The expected classification, written independently of the implementation's dict so a
# copy-paste error in either one shows up as a failure rather than agreeing with itself.
EXPECTED = {
    # acting — 10 states [item 2382]
    "STARTING": StateClass.ACTING,
    "EXECUTE": StateClass.ACTING,
    "COMPLETING": StateClass.ACTING,
    "RESETTING": StateClass.ACTING,
    "HOLDING": StateClass.ACTING,
    "UNHOLDING": StateClass.ACTING,
    "PAUSING": StateClass.ACTING,
    "RESUMING": StateClass.ACTING,
    "STOPPING": StateClass.ACTING,
    "ABORTING": StateClass.ACTING,
    # waiting — 6 states [item 2387]
    "IDLE": StateClass.INITIAL,
    "HELD": StateClass.INTERRUPTED,
    "PAUSED": StateClass.INTERRUPTED,
    "COMPLETED": StateClass.TERMINAL_NORMAL,
    "STOPPED": StateClass.TERMINAL_ABNORMAL,
    "ABORTED": StateClass.TERMINAL_ABNORMAL,
}


def test_every_table_14_state_is_classified():
    """All 16, none missing, none invented. [2658-4:2022] Table 14."""
    assert len(ServiceState) == 16
    assert set(EXPECTED) == {s.name for s in ServiceState}


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_classification(name: str, expected: StateClass):
    assert classify(ServiceState[name]) is expected


def test_acting_and_waiting_partition_the_16():
    """[item 2381] "two general types" — every state is exactly one of them."""
    acting = {s for s in ServiceState if is_acting(s)}
    waiting = {s for s in ServiceState if is_waiting(s)}
    assert len(acting) == 10
    assert len(waiting) == 6
    assert acting | waiting == set(ServiceState)
    assert acting & waiting == set()


def test_execute_is_acting_despite_its_name():
    """[DERIVED] item 2382's literal test is "name ending in ING"; 2658-4 renamed
    ISA-88's RUNNING to EXECUTE. Table B.2's RUNNING row settles the substance."""
    assert is_acting(ServiceState.EXECUTE)


def test_final_states_are_exactly_the_three():
    """[item 3447] "normal completion (COMPLETE) or abnormal termination (STOPPED or
    ABORTED)" — gate #1 of the step model fires on these and nothing else."""
    assert {s for s in ServiceState if is_final(s)} == {
        ServiceState.COMPLETED,
        ServiceState.STOPPED,
        ServiceState.ABORTED,
    }


def test_idle_is_not_final():
    """[item 2391] IDLE is the *Initial* State, not a Final State. A step that reads
    IDLE has not completed — it has not started."""
    assert not is_final(ServiceState.IDLE)
    assert classify(ServiceState.IDLE) is StateClass.INITIAL


def test_interrupted_states_are_recoverable_only():
    """[items 2341-2352] PAUSE and HOLD are the recoverable levels; STOP and ABORT are
    not. So HELD/PAUSED must never be lumped in with the terminal states."""
    interrupted = {s for s in ServiceState if classify(s) is StateClass.INTERRUPTED}
    assert interrupted == {ServiceState.HELD, ServiceState.PAUSED}
    assert not any(is_final(s) for s in interrupted)


def test_unclassified_state_raises_rather_than_defaulting():
    """The no-default-arm guarantee: `classify` must not invent an answer."""
    with pytest.raises(KeyError):
        classify("EXECUTE")  # type: ignore[arg-type]  # a name, not a ServiceState


def test_exhaustiveness_check_catches_a_missing_state():
    """Simulate a future Table 14 addition: the guard must reject it, not default it."""
    from orchestrion.state import classification

    original = classification._CLASS
    try:
        classification._CLASS = {
            k: v for k, v in original.items() if k is not ServiceState.HELD
        }
        with pytest.raises(RuntimeError, match="unclassified ServiceState"):
            classification._check_exhaustive()
    finally:
        classification._CLASS = original
