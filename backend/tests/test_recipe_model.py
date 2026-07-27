"""Master-recipe model — structure + validation ([IEC 61512-1] §6.2/§6.3-shaped)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrion.recipe.model import (
    END,
    And,
    Elapsed,
    Header,
    MasterRecipe,
    Or,
    RecipeStep,
    StateReached,
    Transition,
    ValueThreshold,
)

# A valid two-step linear recipe: run s1 on PEA 1, then s2 on PEA 2 once s1 completes.
VALID = {
    "header": {"name": "Batch-42", "version": 1, "author": "Marwen"},
    "formula": {"stir_minutes": 5.0},
    "steps": [
        {"id": "s1", "pea_id": 1, "service": "Stirring", "procedure_id": 1, "params": {"Duration": 300.0}},
        {"id": "s2", "pea_id": 2, "service": "Stirring", "procedure_id": 2},
    ],
    "transitions": [
        {"from_ids": ["s1"], "to_ids": ["s2"],
         "condition": {"type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED"}},
        {"from_ids": ["s2"], "to_ids": [END],
         "condition": {"type": "StateReached", "pea_id": 2, "service": "Stirring", "state": "COMPLETED"}},
    ],
}


def test_valid_recipe_round_trips() -> None:
    recipe = MasterRecipe.model_validate(VALID)
    assert recipe.header.name == "Batch-42"
    assert [s.id for s in recipe.steps] == ["s1", "s2"]
    assert isinstance(recipe.transitions[0].condition, StateReached)
    assert recipe.transitions[0].condition.state == "COMPLETED"
    # JSON round-trip is lossless (the persisted form is this JSON).
    assert MasterRecipe.model_validate(recipe.model_dump()) == recipe


def test_end_sentinel_allowed_as_target() -> None:
    recipe = MasterRecipe.model_validate(VALID)
    assert END in recipe.transitions[-1].to_ids  # finishing the recipe is legal


def _recipe(**over) -> dict:
    data = {**VALID, **over}
    return data


def test_duplicate_step_id_rejected() -> None:
    steps = [
        {"id": "s1", "pea_id": 1, "service": "Stirring", "procedure_id": 1},
        {"id": "s1", "pea_id": 2, "service": "Stirring", "procedure_id": 1},
    ]
    with pytest.raises(ValidationError, match="duplicate step id"):
        MasterRecipe.model_validate(_recipe(steps=steps, transitions=[]))


def test_transition_to_unknown_step_rejected() -> None:
    bad = [{"from_ids": ["s1"], "to_ids": ["nope"],
            "condition": {"type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED"}}]
    with pytest.raises(ValidationError, match="unknown step id 'nope'"):
        MasterRecipe.model_validate(_recipe(transitions=bad))


def test_transition_from_unknown_step_rejected() -> None:
    bad = [{"from_ids": ["ghost"], "to_ids": ["s2"],
            "condition": {"type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED"}}]
    with pytest.raises(ValidationError, match="unknown step id 'ghost'"):
        MasterRecipe.model_validate(_recipe(transitions=bad))


def test_empty_transition_endpoints_rejected() -> None:
    bad = [{"from_ids": [], "to_ids": ["s2"],
            "condition": {"type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED"}}]
    with pytest.raises(ValidationError, match="at least one from-step"):
        MasterRecipe.model_validate(_recipe(transitions=bad))


def test_end_reserved_as_step_id() -> None:
    steps = [{"id": END, "pea_id": 1, "service": "Stirring", "procedure_id": 1}]
    with pytest.raises(ValidationError, match="reserved sentinel"):
        MasterRecipe.model_validate(_recipe(steps=steps, transitions=[]))


def test_widened_condition_union_round_trips() -> None:
    recipe = {
        "header": {"name": "conds"},
        "steps": [{"id": "s1", "pea_id": 1, "service": "Stirring", "procedure_id": 1}],
        "transitions": [{"from_ids": ["s1"], "to_ids": [END], "condition": {
            "type": "Or", "conditions": [
                {"type": "ValueThreshold", "pea_id": 1, "value_name": "Temp", "op": ">", "threshold": 60.0},
                {"type": "And", "conditions": [
                    {"type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED"},
                    {"type": "Elapsed", "seconds": 5.0}]}]}}],
    }
    m = MasterRecipe.model_validate(recipe)
    top = m.transitions[0].condition
    assert isinstance(top, Or)
    assert isinstance(top.conditions[0], ValueThreshold)
    assert isinstance(top.conditions[1], And)
    assert isinstance(top.conditions[1].conditions[1], Elapsed)
    assert MasterRecipe.model_validate(m.model_dump()) == m  # tagged union round-trips


def test_condition_requires_a_known_type() -> None:
    bad = {
        "header": {"name": "x"},
        "steps": [{"id": "s1", "pea_id": 1, "service": "Stirring", "procedure_id": 1}],
        # condition without a "type" discriminator cannot be resolved
        "transitions": [{"from_ids": ["s1"], "to_ids": [END],
                         "condition": {"pea_id": 1, "service": "Stirring", "state": "COMPLETED"}}],
    }
    with pytest.raises(ValidationError):
        MasterRecipe.model_validate(bad)


def test_step_ui_positions_round_trip() -> None:
    # x/y are optional UI layout; default None, and persist through a JSON round-trip.
    step = RecipeStep(id="a", pea_id=1, service="Stirring", procedure_id=1)
    assert step.x is None and step.y is None
    placed = RecipeStep(id="b", pea_id=1, service="Stirring", procedure_id=1, x=120.5, y=48.0)
    back = RecipeStep.model_validate(placed.model_dump())
    assert back.x == 120.5 and back.y == 48.0


def test_step_and_condition_construct_directly() -> None:
    # The typed classes are usable directly, not only via dict validation.
    step = RecipeStep(id="a", pea_id=1, service="Stirring", procedure_id=1)
    cond = StateReached(pea_id=1, service="Stirring", state="EXECUTE")
    recipe = MasterRecipe(
        header=Header(name="one-step"),
        steps=[step],
        transitions=[Transition(from_ids=["a"], to_ids=[END], condition=cond)],
    )
    assert recipe.steps[0].service == "Stirring"
