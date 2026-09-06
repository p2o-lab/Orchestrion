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

from typing import Annotated, Literal, Union

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
    # UI-only canvas position for the builder — [design-not-dictated], non-normative. The
    # engine and conditions ignore it; it exists so a saved recipe keeps its layout.
    x: float | None = None
    y: float | None = None


# ── transition conditions ([design-not-dictated] — our scheme; state names are standard) ──
# A tagged union: every member carries a `type` discriminator, so JSON must name its type
# (e.g. {"type": "StateReached", ...}). `And`/`Or` nest, so a condition is a tree.

class StateReached(BaseModel):
    """A service has reached a given state. The `state` value is standard — a [2658-4 Table 14]
    service-state name (e.g. "COMPLETED"), i.e. the ISA-88 procedural-element state model."""

    type: Literal["StateReached"] = "StateReached"
    pea_id: int
    service: str
    state: str


class ValueThreshold(BaseModel):
    """A live process value crosses a threshold. `value_name` is the value's TagName as the PEA
    publishes it — the key in the live snapshot's `values` (engine reads `registry.snapshot`)."""

    type: Literal["ValueThreshold"] = "ValueThreshold"
    pea_id: int
    value_name: str
    op: Literal["<", "<=", ">", ">=", "==", "!="]
    threshold: float


class Always(BaseModel):
    """The step completing is the only gate — nothing further to wait for.

    Under the two gates ([IEC 61512-1] item 1341, `POL_Step_Model_ISA88.md` §3) a transition
    already requires its predecessors to have **terminated**. For a step whose procedure ends
    by itself, that is usually the whole story, and the author has nothing to add — but
    `Transition.condition` is required, so there has to be a way to say "nothing". This is
    it. Drawn `=1` in GRAFCET ([IEC 60848] §4.3.3: the transition-condition is *"a logical
    expression which is true or false"*; the constant-true one is legal).

    ⚠ **Not valid on a transition with a *continuous* step in its `from_ids`.** There the
    receptivity **is** the completion criterion (step model §2), so `Always` would start the
    service and complete it in the same instant. Enforced server-side in `api/recipes.py`
    (unit 7) and in the builder (`POL_Recipe_Chart_GRAFCET.md` §4).
    """

    type: Literal["Always"] = "Always"


class Elapsed(BaseModel):
    """The transition's from-step(s) have been active for at least `seconds`.

    "Active" depends on the procedure kind, from one rule (step model §9): a transition is
    enabled when its last from-step became *eligible* — termination for a self-completing
    step, activation for a continuous one. So this is a **dwell after it finishes** in the
    first case and a **duration it runs for** in the second.
    """

    type: Literal["Elapsed"] = "Elapsed"
    seconds: float


class And(BaseModel):
    """All sub-conditions hold.

    `min_length=1`: `all([])` is **True**, so an empty `And` would be a silent `Always` —
    including on a continuous step's transition, where `Always` is forbidden precisely
    because it completes the service the instant it starts.
    """

    type: Literal["And"] = "And"
    conditions: list["Condition"] = Field(min_length=1)


class Or(BaseModel):
    """At least one sub-condition holds.

    `min_length=1`: `any([])` is **False**, so an empty `Or` is a receptivity that can
    never hold — a run that waits for ever, with no global timeout to bound it
    (`POL_Step_Model_ISA88.md` §11).
    """

    type: Literal["Or"] = "Or"
    conditions: list["Condition"] = Field(min_length=1)


# The condition on a transition — discriminated on `type` (robust vs. field-guessing).
# Widening it is purely additive: because the union is discriminated, an existing stored
# recipe names its own type and cannot change meaning when a new member is added.
Condition = Annotated[
    Union[Always, StateReached, ValueThreshold, Elapsed, And, Or],
    Field(discriminator="type"),
]


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
    # UI-only canvas position, exactly like `RecipeStep.x`/`.y` — [design-not-dictated] and
    # non-normative. The engine and conditions ignore them.
    #
    # `POL_Recipe_Chart_GRAFCET.md` §9 originally gave a transition no coordinates at all, on
    # the grounds that its place is a *function* of its neighbours (§6 needs it to span its
    # branches) — so it was computed on every load. That is a fine default and it stays the
    # fallback, but it is not a fine *answer* to an author who dragged a transition somewhere
    # deliberate: the position was silently discarded and the chart rearranged itself on the
    # next visit. §9 called adding these "purely additive"; this is that addition.
    x: float | None = None
    y: float | None = None


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
            # A repeated endpoint is always an authoring mistake, and not a harmless one:
            # a duplicated `from_id` would have the engine `RESET` the same service twice
            # when the transition clears.
            for side, ids in (("from_ids", t.from_ids), ("to_ids", t.to_ids)):
                if len(set(ids)) != len(ids):
                    raise ValueError(f"transition {side} contains a duplicate: {ids}")
        return self


# Resolve forward references now that every class exists (And/Or nest via `Condition`, and
# Transition/MasterRecipe reference the `Condition` union).
And.model_rebuild()
Or.model_rebuild()
Transition.model_rebuild()
MasterRecipe.model_rebuild()
