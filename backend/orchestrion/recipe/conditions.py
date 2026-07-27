"""Evaluate a transition `Condition` against the live plant state.

Pure and synchronous (no I/O) → trivially unit-testable. This first increment handles only
`StateReached` (all the M5.1 sequential engine needs). M5.2 widens the `Condition` union
(`ValueThreshold` / `Elapsed` / `And` / `Or`) and will pass a richer context (live values,
elapsed time) alongside the state lookup.

[design-not-dictated] — the condition scheme is our design (the orchestration layer is not yet
standardized); the `state` *value* compared here is a standard [2658-4 Table 14] state name.
"""

from __future__ import annotations

from collections.abc import Callable

from orchestrion.recipe.model import Condition, StateReached

# A lookup of the live service state: (pea_id, service_name) -> Table-14 state name, or None
# if that PEA is not connected / that service is not (yet) reporting.
StateOf = Callable[[int, str], "str | None"]


def is_met(condition: Condition, state_of: StateOf) -> bool:
    """Whether `condition` currently holds, given a live-state lookup."""
    if isinstance(condition, StateReached):
        return state_of(condition.pea_id, condition.service) == condition.state
    raise TypeError(f"unsupported condition type: {type(condition).__name__}")
