"""Condition evaluation — StateReached / ValueThreshold / Elapsed / And / Or (pure)."""

from __future__ import annotations

from orchestrion.recipe.conditions import EvalContext, is_met
from orchestrion.recipe.model import And, Elapsed, Or, StateReached, ValueThreshold


def _ctx(*, states=None, values=None, elapsed=0.0) -> EvalContext:
    states = states or {}
    values = values or {}
    return EvalContext(
        state_of=lambda p, s: states.get((p, s)),
        value_of=lambda p, n: values.get((p, n)),
        elapsed=elapsed,
    )


def test_state_reached() -> None:
    cond = StateReached(pea_id=1, service="Stirring", state="COMPLETED")
    assert is_met(cond, _ctx(states={(1, "Stirring"): "COMPLETED"}))
    assert not is_met(cond, _ctx(states={(1, "Stirring"): "EXECUTE"}))
    assert not is_met(cond, _ctx())  # not reporting yet


def test_value_threshold_operators() -> None:
    def cond(op: str, thr: float) -> ValueThreshold:
        return ValueThreshold(pea_id=1, value_name="Temp", op=op, threshold=thr)

    ctx = _ctx(values={(1, "Temp"): 60.0})
    assert is_met(cond(">", 50), ctx)
    assert not is_met(cond(">", 60), ctx)
    assert is_met(cond(">=", 60), ctx)
    assert is_met(cond("<", 61), ctx)
    assert is_met(cond("<=", 60), ctx)
    assert is_met(cond("==", 60), ctx)
    assert is_met(cond("!=", 59), ctx)
    # a missing value never satisfies a threshold
    assert not is_met(cond(">", 0), _ctx())


def test_elapsed() -> None:
    cond = Elapsed(seconds=5.0)
    assert not is_met(cond, _ctx(elapsed=4.9))
    assert is_met(cond, _ctx(elapsed=5.0))
    assert is_met(cond, _ctx(elapsed=10.0))


def test_and_or_nesting() -> None:
    hot = ValueThreshold(pea_id=1, value_name="Temp", op=">", threshold=60.0)
    done = StateReached(pea_id=1, service="Stirring", state="COMPLETED")

    both = And(conditions=[hot, done])
    either = Or(conditions=[hot, done])

    hot_only = _ctx(values={(1, "Temp"): 70.0}, states={(1, "Stirring"): "EXECUTE"})
    both_true = _ctx(values={(1, "Temp"): 70.0}, states={(1, "Stirring"): "COMPLETED"})
    neither = _ctx(values={(1, "Temp"): 10.0}, states={(1, "Stirring"): "EXECUTE"})

    assert not is_met(both, hot_only) and is_met(both, both_true)
    assert is_met(either, hot_only) and not is_met(either, neither)

    # nested: (hot AND done) OR elapsed>=5
    nested = Or(conditions=[both, Elapsed(seconds=5.0)])
    assert is_met(nested, _ctx(elapsed=6.0))  # via the Elapsed branch
    assert is_met(nested, both_true)          # via the And branch
    assert not is_met(nested, neither)
