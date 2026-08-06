"""Evaluate a transition `Condition` against the live plant state.

Pure and synchronous (no I/O) → trivially unit-testable. Handles the full `Condition` union:
`StateReached` / `ValueThreshold` / `Elapsed` and the boolean `And` / `Or` (which nest).

[design-not-dictated] — the condition scheme is our design (the orchestration layer is not yet
standardized); the `state` values compared are standard [2658-4 Table 14] state names.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass

from orchestrion.recipe.model import (
    Always,
    And,
    Condition,
    Elapsed,
    Or,
    StateReached,
    ValueThreshold,
)

# Live lookups the engine supplies from `registry.snapshot(pea_id)`.
StateOf = Callable[[int, str], "str | None"]  # (pea_id, service)    -> Table-14 state name
ValueOf = Callable[[int, str], "float | None"]  # (pea_id, value_name) -> live value

_OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
}


@dataclass(frozen=True)
class EvalContext:
    """Everything a condition is evaluated against at one instant."""

    state_of: StateOf
    value_of: ValueOf
    elapsed: float = 0.0  # seconds the transition's from-step(s) have been active


def is_met(condition: Condition, ctx: EvalContext) -> bool:
    """Whether `condition` currently holds, given the live context."""
    if isinstance(condition, Always):
        return True  # gate 1 (the step terminated) is the only gate — step model §3
    if isinstance(condition, StateReached):
        return ctx.state_of(condition.pea_id, condition.service) == condition.state
    if isinstance(condition, ValueThreshold):
        value = ctx.value_of(condition.pea_id, condition.value_name)
        return value is not None and _OPS[condition.op](float(value), condition.threshold)
    if isinstance(condition, Elapsed):
        return ctx.elapsed >= condition.seconds
    if isinstance(condition, And):
        return all(is_met(c, ctx) for c in condition.conditions)
    if isinstance(condition, Or):
        return any(is_met(c, ctx) for c in condition.conditions)
    raise TypeError(f"unsupported condition type: {type(condition).__name__}")
