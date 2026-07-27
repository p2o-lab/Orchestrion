"""The master-recipe data model — ISA-88-shaped, serialized as our own JSON.

Grounded in IEC 61512-1 (ISA-88), read directly from the standard (Rule 1):
- A recipe's contents are five categories (§6.3.1 General): **header** (§6.3.2),
  **formula** (§6.3.3), **equipment requirements** (§6.3.4), **procedure** (§6.3.5), and
  **other information** (§6.3.6).
- The **formula** (§6.3.3) is the recipe's parameters — process inputs, process parameters
  (temperature/pressure/time…), and process outputs.
- The **procedure** (§6.3.5) is built from *procedural elements* structured by the procedural
  control model levels — procedure > unit procedure > operation > **phase** (§5). A *phase* is
  the lowest element, the one that commands equipment. In MTP a PEA **service (procedure)** IS
  an ISA-88 phase / equipment procedural element (research §5, WG-2024 mapping).
- **Recipe types** (§6.2): general > site > master > control. This module models the **master
  recipe** — the one an operator authors for a plant configuration. The runtime *control
  recipe* (the master bound to the actual connected PEAs at run time) is a later increment.

DESIGN-NOT-DICTATED — flagged per Rule 1, because the orchestration layer is not yet a
finished standard (VDI/VDE/NAMUR 2658 standardizes the PEA interface, not the recipe logic):
- We represent the procedure as an explicit graph of `RecipeStep`s joined by `Transition`s
  carrying a `Condition` (an SFC-style steps+transitions rendering, IEC 61131-3-flavoured).
  ISA-88 structures a procedure as nested procedural elements; this explicit
  step/transition/condition shape is our design choice, not an ISA-88 literal.
- A `RecipeStep` binds directly to an explicit PEA (`pea_id`) + service + procedure. ISA-88
  keeps this as an equipment *requirement* (§6.3.4) so a master recipe can stay
  equipment-agnostic and be bound later; we bind explicitly for now (capability-based binding
  is parked — design doc §9). Equipment requirements (§6.3.4) are therefore not modelled yet.
- The `Condition` scheme is our design. Only `StateReached` exists in this first increment
  (all M5.1's sequential engine needs); `ValueThreshold` / `Elapsed` / boolean `And`/`Or`
  arrive in M5.2. The `state` *value* it matches is standard, however: a [2658-4 Table 14]
  service-state name, which is the ISA-88 procedural-element state model (research §4.3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# The sentinel a transition may point to instead of a step id: the recipe is finished.
END = "END"


class Header(BaseModel):
    """Administrative information about the recipe — [IEC 61512-1 §6.3.2]."""

    name: str
    version: int = 1
    author: str = ""
    product: str = ""  # product identification / description (§6.3.2)


# The formula — [IEC 61512-1 §6.3.3]. A flat parameter map for now (name -> value); ISA-88
# distinguishes process inputs / process parameters / process outputs, a refinement deferred.
Formula = dict[str, float]


class RecipeStep(BaseModel):
    """One phase of the procedure (§6.3.5 / §5), bound to a PEA service procedure.

    [design-not-dictated] the explicit PEA binding; ISA-88 would express this as an equipment
    requirement (§6.3.4). `params` are the controlled values assigned to the procedure's
    parameters at Start (MTP §8.1.3 controlled value assignment).
    """

    id: str
    pea_id: int
    service: str
    procedure_id: int
    params: dict[str, float] = Field(default_factory=dict)


class StateReached(BaseModel):
    """A transition condition: a service has reached a given state.

    [design-not-dictated] representation. The `state` value is standard — a [2658-4 Table 14]
    service-state name (e.g. "COMPLETED"), i.e. the ISA-88 procedural-element state model.
    """

    type: str = "StateReached"  # discriminator; the union widens in M5.2
    pea_id: int
    service: str
    state: str


# The condition on a transition. A one-member alias for now; M5.2 widens it into a
# discriminated union (StateReached | ValueThreshold | Elapsed | And | Or). Because every
# member carries a `type` discriminator, widening later needs no change to stored recipes.
Condition = StateReached


class Transition(BaseModel):
    """An edge of the procedure graph (SFC-style, [design-not-dictated]): once `condition`
    holds, control advances from every step in `from_ids` to every step in `to_ids`.

    Several `to_ids` = a parallel divergence; several `from_ids` = a join (all must be done).
    `to_ids` may contain the `END` sentinel to finish the recipe. (Parallel/join are honoured
    by the engine in M5.3; the model already allows them so the schema is stable.)
    """

    from_ids: list[str]
    to_ids: list[str]
    condition: Condition


class MasterRecipe(BaseModel):
    """A master recipe — [IEC 61512-1 §6.2]: header + formula + procedure (steps+transitions)."""

    header: Header
    formula: Formula = Field(default_factory=dict)
    steps: list[RecipeStep]
    transitions: list[Transition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_structure(self) -> MasterRecipe:
        # Step ids must be unique — they are the graph's node keys.
        ids = [s.id for s in self.steps]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate step id(s): {sorted(duplicates)}")
        if END in ids:
            raise ValueError(f"{END!r} is a reserved sentinel and cannot be a step id")

        # Every transition endpoint must resolve to a real step (or END, only as a target).
        known = set(ids)
        for t in self.transitions:
            for src in t.from_ids:
                if src not in known:
                    raise ValueError(f"transition from unknown step id {src!r}")
            for dst in t.to_ids:
                if dst != END and dst not in known:
                    raise ValueError(f"transition to unknown step id {dst!r}")
            if not t.from_ids or not t.to_ids:
                raise ValueError("a transition needs at least one from-step and one to-step")
        return self
