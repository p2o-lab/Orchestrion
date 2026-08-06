# Orchestrion — The Recipe Chart (GRAFCET / IEC 60848)

**Status: DESIGN AUTHORITY for the recipe builder chart.**
Written 2026-08-04. Supersedes §2.5 of [`POL_Recipe_Engine_Design.md`](POL_Recipe_Engine_Design.md)
("boxes = steps, arrows = transitions" — **wrong**, see §1) and the AND/OR bar-node work in
[`progress/009`](progress/009_m5_recipe_engine.md). Rationale and build order:
[`progress/010`](progress/010_m5_step_model_correction.md).

**Nothing here is implemented yet.** The current builder contradicts this document.

Read [`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md) first — the chart's semantics depend on it.

---

## 0. What we actually hold of IEC 60848, and the tags

**IEC 60848:2013** was obtained 2026-08-04 as the **official public preview**. We had never held this
document before; [`009`](progress/009_m5_recipe_engine.md) records it as "not in `../standards/`".

**Re-obtained and re-read 2026-08-05**, this time downloaded to the session scratchpad and extracted,
so every quote below is now checkable rather than remembered:
`https://cdn.standards.iteh.ai/samples/19077/a0175aea9c504229beb0d6b01861b5d0/IEC-60848-2013.pdf`
— 15 PDF pages. **Treat it exactly like `../standards/`: scratchpad only, never the repo.**

**What the preview contains: front matter + standard pages 8–13 = §1, §2, §3.1 (all 15 definitions),
§3.2, §4.1, §4.2, §4.3.1–§4.3.3, and §4.4 up to the word "Consequences:", where it stops mid-clause.**
Plus **Figure 1** and **Figure 2**, both legible.

**Everything from §4.4's consequence list onward — §4.5.x evolution rules, §5's symbol Tables 1–4, all
of §6, §7 and the annexes — exists only as a table-of-contents title.** Clause numbers and names,
**not one word of their text**. §4.3.1 confirms where the symbols live: *"Symbols related to GRAFCET
elements … are presented and exemplified in **Tables 1 to 4 in Clause 5**"* — standard page 19+,
outside the preview.

> **The TOC was checked against every `[TITLE-ONLY]` attribution in this document on 2026-08-05, and
> all of them are correct:** §4.5.2 *Initial situation* · §4.5.3 *Clearing of a transition* ·
> §6.2.3 *Selection of sequences* · §6.2.4 *Step skip* · §6.2.5 *Backward sequence skip* ·
> §6.2.6 *Activation of parallel sequences* · §6.2.7 *Synchronization of sequences* ·
> §6.2.8 *Synchronization and activation of parallel sequences* · §6.3.1 *Starting of a sequence by a
> source step* · §6.3.2 *End of a sequence by a pit step* · §6.3.3 *Starting of a sequence with a
> source transition* · §6.3.4 *End of a sequence by a pit transition*. The titles are right; the text
> is still unread.
>
> **One clause the TOC revealed that this document never mentioned: §6.2.2 *"Cycle of a single
> sequence"*.** It matters — see §2 and §10.

| tag | meaning |
|---|---|
| **`[CITED]`** | the clause text is quoted. Verifiable directly. |
| **`[TITLE-ONLY]`** | clause **number and name only**; meaning inferred *from its title*. **A guess wearing a clause number.** |
| **`[SEARCHED]`** | secondary sources agreeing with each other; the clause itself is unread. |
| **`[DERIVED]`** | inference *from* cited clauses. |
| **`[OURS]`** | a judgement call with no standard behind it. |

> ### ⛔ `BLOCKED ON STANDARD: IEC 60848:2013 §5 (Tables 1–4) and the §6 figures`
> The **structures** are sound — §4.3.2, §4.3.3 and §4.4, all read in full. How they are **drawn** is
> still largely unverified. **Narrowed 2026-08-05** by rendering Figure 2 rather than only extracting
> its text:
>
> | glyph | status |
> |---|---|
> | **double-border initial step** | **seen** in Figure 2 (step 1 double, steps 2-4 single) — still `[DERIVED]`, since *that it means "initial"* is read off the picture, not a clause |
> | **transition = a short tick across the directed link** | **seen** in Figure 2, transitions (1)-(4) |
> | **step = a rectangle, link = a vertical arrowed line** | **seen** in Figure 2 |
> | `=1` receptivity · branch bars (single vs double) · pit-transition cap | **still from memory** |
>
> Tables 1–4 in Clause 5 remain the authority and remain unread, so **no glyph may be defended as
> standard-conformant** — but three of them are no longer guesses.

---

## 1. Two node kinds. Nothing else.

**`[CITED]`** The element list is closed at **five** items, enumerated by **§4.3.2 + §4.3.3**:

> **§4.3.2 Structure** — *"The structure comprises the following basic items:"*
> • **Step** (definition 3.1.8, symbol 1) • **Transition** (definition 3.1.10, symbol 7)
> • **Directed link** (definition 3.1.2, symbol 10)
>
> **§4.3.3 Elements for interpretation** — *"The following elements are used for the interpretation:"*
> • **Transition-condition** (definition 3.1.11, symbol 13) • **Action** (definition 3.1.1)

> **⚠ Re-cited 2026-08-05 — the conclusion is unchanged and now better sourced.** This section used to
> attribute the closed list to **§3.1**, tagged `[CITED]`. **§3.1 is a glossary** — *"Terms in the
> GRAFCET"*, entries 3.1.1 through 3.1.15 — and it never says the list is closed. What is true of §3.1
> is narrower and still useful: **exactly five of its fifteen entries are defined as "GRAFCET language
> element"** — action (3.1.1), directed link (3.1.2), step (3.1.8), transition (3.1.10),
> transition-condition (3.1.11). The other ten (grafcet chart, input/internal event, interpretation,
> situation, transient evolution, and the four variable kinds) are not elements.
> **§4.3.2/§4.3.3 say it outright with "comprises the following basic items", so cite those.**

**`[CITED]`** §4.4 syntax rule: *"Step transition and transition step alternation **shall** always be
respected whatever the sequence."*

**`[CITED]`** §4.2 states the same shape independently, and adds the multiplicity: *"The evolution of
one set of steps to another is translated by one or several transitions, each characterized by: • its
preceding steps, • its succeeding steps, • its associated transition-condition."* — followed by
*"NOTE These reasons lead to the syntax rule enforcing the alternation step-transition."*

So the canvas holds **steps** and **transitions**, and nothing else.
**No START node. No END node. No AND node. No OR node.**

- **`[CITED]`** §4.3.2/§4.3.3 (the closed five) and §4.3.2 again (AND/OR are link *multiplicity*, §5 below).
- **`[CITED]`** ISA-88 §5.3.2 — the procedural control model's levels are procedure → unit procedure →
  operation → phase. **There is no start or end element.**
- **`[CITED]`** ISA-88 items 2391-2393: `IDLE` = Initial State, `COMPLETE`/`STOPPED`/`ABORTED` = Final
  States — these are **run states, not chart nodes.** They belong in the execution view's status bar,
  never on the canvas.

**A transition is a node**, not an arrow. **`[CITED]`** §4.3.3 — the transition-condition is *"a logical
expression which is true or false"*, associated with **the transition**. Never on a link. Arrows are
*directed links* (§3.1.2) and carry nothing.

> This is what `POL_Recipe_Engine_Design.md` §2.5 got wrong ("boxes = steps, **arrows = transitions**")
> and what the AND/OR bar nodes in `009` got wrong. Both modelled a drawing convention as a graph
> element — which is why the bars needed patch after patch of validation.

---

## 2. The initial step

**`[TITLE-ONLY]`** §4.5.2 is named *"Initial situation"* — text unread. What we actually have:
**`[CITED]`** §3.1.7 defines *situation* as *"state of the system … characterized by the active steps at
a given instant"*, and Figure 2 (seen) draws step 1 with a **double border**. That the double square
marks the initial step is **`[DERIVED]` from the figure**, not read from a clause.

**`[DERIVED]` We infer it from topology** — the step no transition targets — and draw the double border
live, rather than having the author declare it. This matches `engine.py:92` exactly (*"Start steps =
those that are never a transition target"*), so it serializes with **zero backend change**.
**But inferring is not what §4.5.2 describes.**

> ### ⛔ Corrected 2026-08-05 — the inference is wrong for any cyclic chart
>
> This section used to end *"…and on a well-formed chart the two agree."* **That is false, and the
> standard's own illustration is the counterexample.**
>
> **`[DERIVED]` from Figure 2, rendered and read directly** (page 15 of the preview PDF): step 1 is
> drawn with a **double border**, *and* the leftmost directed link runs from below transition (4) back
> **up into step 1**. Figure 2 is a **cycle**: `1 → (1) → 2 → (2) → 3 → (3) → 4 → (4) → 1`.
>
> So in the standard's own example the initial step **is** a transition target. Run our rule over it
> and you get **zero** initial steps — the exact case this section already flags as producing an
> instant false `completed`.
>
> **`[TITLE-ONLY]` corroboration:** the TOC names **§6.2.2 *"Cycle of a single sequence"*** as a basic
> structure, alongside §6.2.4 *Step skip* and §6.2.5 *Backward sequence skip*. A cycle is not an edge
> case in GRAFCET; it is a named, ordinary shape.
>
> **Consequence:** the initial step **cannot be derived from topology in the general case**. Either
>
> - **(a)** the recipe declares its initial step explicitly (a field on `MasterRecipe`, or a flag on
>   `RecipeStep`) — correct, matches what §4.5.2 presumably describes, and costs a backend change; or
> - **(b)** we forbid cycles, and topology-inference stays valid **by construction** — cheap, honest,
>   but it rejects charts the standard plainly permits, and must be *stated* as our restriction rather
>   than presented as GRAFCET.
>
> **This is the same decision as §10, arrived at from the other side.** It is no longer a "nice to
> settle before unit 12" — it is a prerequisite for the chart model, because the initial step is how a
> run starts. **Settle it before unit 3**, since (a) changes `MasterRecipe`.

**`[OURS]` Exactly one initial step is required.** §3.1.7's *situation* is a set of active steps
(plural), so several are presumably legal — but the settling clause is unread. Either way, several is a
hard error: **a narrowing chosen for safety**, not something the standard was read to permit or forbid.

Two silent engine behaviours become validation errors — **a warning while building, a blocker on
save/run**, so a half-built chart can sit on the canvas:

- **Zero initial steps** (a closed loop) → `run.active` starts empty → the `while` at `engine.py:99`
  never runs → line 126 reports **`completed` instantly having done nothing.** Guard in the engine too.
- **Several initial steps** → the engine starts **all** of them at once on live equipment.
  *(Verified 2026-08-05 by reading `engine.py:92-96`: it activates every step not in `targets`, with
  no cardinality check anywhere.)*

> **⚠ Added 2026-08-05 — both guards must be enforced SERVER-SIDE, not only in the builder.**
> A recipe can be `POST`ed straight to the API, bypassing the canvas entirely — which is exactly how
> the unit-7 integration test works. The builder's validation is an authoring aid; it is not a
> safety boundary. This belongs beside the existing checks in `api/recipes.py:111`
> (`_validate_against_project`), which today verifies steps and conditions but **nothing structural
> about the graph**. Units 9–12 are frontend, so without this note the server-side half has no owner.

---

## 3. The end of a branch

**`[TITLE-ONLY]`** §6.3.4 is named *"End of a sequence by a pit transition"* — text unread; that a "pit
transition" has no successor is read **off the title**. Corroborated by the clause list's shape
(§6.3.1/§6.3.3 name *source* step/transition — a start with nothing before; §6.3.2/§6.3.4 name *pit*
step/transition — an end with nothing after) and by ISA-88 item 1337's *"defined beginning and end"*,
held in full.

An unwired transition output **is** the end. No toggle, no gesture. Serialized as `to_ids: ["END"]`
(the existing sentinel, `model.py:40`).

**`[OURS]`** drawn with a **solid cap**; a not-yet-wired transition draws a **faded open stub**, so a
finished branch is never confused with an unfinished one.

---

## 4. Transitions carry the receptivity

**`[CITED]`** §4.3.3, above — **re-verified verbatim 2026-08-05**: *"Transition-condition (definition:
3.1.11, symbol 13). **Associated with each transition**, the transition-condition is **a logical
expression which is true or false** and which is composed of input variables and/or internal
variables."* The guard lives on the transition node — never on an edge, never on a bar.

**`[OURS]`** Add `Always` to the `Condition` union — purely additive, since the union is discriminated
on `type`, so nothing existing changes meaning:

```python
class Always(BaseModel):
    """Receptivity: the step completing is the only gate. [IEC 60848 §4.3.3]"""
    type: Literal["Always"] = "Always"
```

Plus one line in `conditions.is_met`. **Default for every new transition leaving a self-completing
step** — with completion structural (step model §3), such a transition has nothing to add, yet
`model.py:140` makes `condition` required.

**`[OURS]` A transition leaving a *continuous* step must NOT default to `Always`** — that would start
the service and immediately complete it. For a continuous step the receptivity **is** the completion
criterion (step model §2), so a real one is required: a duration, a threshold, an operator
confirmation. Two things this needs:

- **The builder must know which kind a procedure is.** It already can — `is_self_completing` is on the
  procedure schema (`api/schemas.py:81`, populated at `:140`). No new endpoint.
- **Enforced server-side too, not only in the UI.** A recipe can be `POST`ed straight to the API,
  bypassing the builder — which is exactly how the integration test works. Belongs beside the existing
  checks in `api/recipes.py:111` (`_validate_against_project`), which already resolves each step's PEA
  and service.

---

## 5. AND and OR are drawn, not placed

**`[CITED]`** §4.3.2 — **re-verified verbatim 2026-08-05**: *"Directed link (definition: 3.1.2, symbol
10). A directed link connects **one or several steps to a transition, or a transition to one or
several steps**."* Corroborated by §4.2: a transition is *"characterized by: • its **preceding steps**,
• its **succeeding steps**, • its associated transition-condition"* — plural on both sides.

**The bars are how you *draw* an element with more than one link on a side — never a node.**
The "never a node" conclusion is **`[CITED]`**: it follows from §4.3.2 and §3.1's closed element list,
both read in full.

**`[TITLE-ONLY]`** every §6.2.x row below — clause *names*, not text. **The structure column is derived
from §4.3.2**; the clause numbers are attribution by title.

| clause (title only) | structure | hangs off | backend |
|---|---|---|---|
| §6.2.6 *Activation of parallel sequences* | AND divergence | **one transition**, several steps | `Transition{from:[S1], to:[S2,S3]}` |
| §6.2.7 *Synchronization of sequences* | AND convergence | several steps, **one transition** | `Transition{from:[S2,S3], to:[S4]}` |
| §6.2.3 *Selection of sequences* | OR | **one step**, several transitions | several `Transition`s sharing a `from` |
| §6.2.8 *Synchronization and activation* | both | one transition, several both sides | `Transition{from:[…], to:[…]}` |

**`[CITED]`** the backend already says exactly this — `model.py:133`: *"Several `to_ids` = a parallel
divergence; several `from_ids` = a join."* **All four forms need no backend change.**

```
   AND divergence              OR divergence
      ┌────┐                      ┌────┐
      │ S1 │                      │ S1 │
      └──┬─┘                      └──┬─┘
         │                           │
      ───┼───  Temp>80           ────┴────      ← the OR rail (single)
      ═════════  ← double bar     │       │
       │      │                 ──┼──   ──┼──   ← a transition per branch
     ┌─┴┐   ┌─┴┐                  │       │
     │S2│   │S3│                ┌─┴┐    ┌─┴┐
     └──┘   └──┘                │S2│    │S3│
                                └──┘    └──┘
   ONE transition,            ONE step,
   2 succeeding steps         2 succeeding transitions
```

### The step model is what makes these work at all

- **AND convergence** — `engine.py:12-13` currently makes the author hand-write
  `And[COMPLETED(S2), COMPLETED(S3)]`, restating as a receptivity what is already structural. With the
  two gates, all from-steps completing **is** gate #1; the receptivity becomes `=1` and the `And`
  disappears.
- **OR divergence** — every branch currently carries the same default "reached COMPLETED", so all go
  true at once and the "choice" is decided by list order. **That is not a selection.** With the two
  gates, the shared part is gate #1 and each branch carries a **real** distinguishing receptivity.

> **⚠ Added 2026-08-05 — both branch forms are undefined when a *continuous* step is involved.**
> Neither this document nor the step model says what happens, and unit 8 (OR arbitration) and unit 3
> (the two gates) both need an answer. See step model §12 items **0b** and **0c**:
>
> - **OR-divergence out of a continuous step** — each branch receptivity *is* the completion criterion
>   (step model §2), so which one triggers the single `COMPLETE`, and what becomes of the others while
>   we await `COMPLETED`?
> - **AND-convergence over mixed kinds** — the join carries **one** receptivity, which would have to be
>   the completion criterion for *every* continuous from-step at once. The "`=1`" answer above is
>   correct **only when every from-step is self-completing**; for a continuous one it would complete it
>   instantly.
>
> The simplest resolution — **forbid a continuous step from having more than one outgoing transition,
> and forbid mixed-kind joins** — is `[OURS]` and costs two validation rules. Decide before unit 3.

---

## 6. How the bars are drawn

**`[OURS]`** **Nodes render their own bars.**

- A **transition** draws a short tick with one link, and a tick **plus a wide double bar spanning its
  branches** with several.
- A **step** grows a **single rail** beneath it when several transitions leave it.

This reproduces GRAFCET's stacked-marks convention rather than fanning edges out of a point.

**Cost:** layout-aware rendering — a node must size its bar from where its branches sit. React Flow
gives handles, not spans, so this is real work in `FlowNodes.tsx`.

**Glyphs unverified** — see the `BLOCKED ON STANDARD` box in §0.

---

## 7. How a branch is authored

**`[OURS]`** **Palette actions on the selected element**, building the wiring rather than dropping a
node. Because AND hangs off a transition and OR off a step (§5), each action **enables only on the
correct element kind** — the palette teaches §4.3.2 instead of letting you violate it:

```
select a TRANSITION →  [+ parallel branch]  enabled  → AND, appends to to_ids
                       [+ selection branch] greyed
select a STEP       →  [+ selection branch] enabled  → OR, adds another outgoing transition
                       [+ parallel branch]  greyed
```

**No new node type is ever created, in either path.**

---

## 8. OR branch arbitration — priority now, exclusivity lint later

**`[SEARCHED]`** — secondary sources only; **§6.2.3 remains unread**. Converging across
[maxicours](https://www.maxicours.com/se/cours/grafcet-avec-selections-de-sequences/) and
[PLC-HMI-SCADAS](https://www.plc-hmi-scadas.com/en/blog/grafcet-guia-completa-diseno-automatizacion/):

- **GRAFCET requires** the branch receptivities to be mutually exclusive and, if they are not, declares
  the chart *faulty and indeterminate*. **It does not arbitrate.**
- **IEC 61131-3 SFC does** arbitrate, via **user-defined priority between branches**.
- IEC 60848 **Annex C** exists to relate the two languages.

**`[OURS]` Adopt SFC arbitration — explicit, visible branch priority.** A step's outgoing transitions
are walked in priority order and **at most one fires**. Exactly one branch is taken; indeterminacy is
impossible.

- **Journal it as SFC arbitration, not GRAFCET conformance.** GRAFCET's own answer is "the chart is
  faulty"; we resolve rather than refuse.
- **No model change.** `MasterRecipe.transitions` is already an ordered list — **priority *is* that
  order.** We surface what exists as a visible, draggable ①②③, instead of an invisible artefact of array
  position that reshuffles on re-save.
- **`[DERIVED]` the firing loop must become deliberate.** Today "only one branch fires" is an
  *accident*: `engine.py:106` iterates every transition and mutates `run.active` mid-loop, so the first
  firing removes the step and the second's guard incidentally fails. Replace with: **group a step's
  outgoing transitions, walk in priority order, fire at most one.** This also removes the
  order-dependent same-tick cascade that mutation-during-iteration currently allows.
- **Deferred — the exclusivity lint.** Detecting *provably* overlapping branches (identical conditions ·
  `Always` on a branch · `Temp>80` vs `Temp>50` on one value · two `StateReached` on one service) is a
  **lint over authoring intent, not a safety mechanism**: such a chart still runs deterministically, it
  just has a silently dead branch. Purely additive whenever it is added.

---

## 9. Layout

**`[OURS]` Transitions are auto-laid-out.** `Transition` gains no `x`/`y`. A transition's position is a
*function* of its neighbours — §6 requires it to span its branches — so auto-layout is the **correct
model, not a compromise**. `RecipeStep` keeps its existing UI-only `x`/`y` (`model.py:72-73`). Adding
transition coordinates later would be purely additive.

---

## 10. ⚠ UNDECIDED — backward links / loops

**This must be settled before the validation rule set is implemented.**

GRAFCET **§6.2.2** *Cycle of a single sequence*, **§6.2.4** *Step skip* and **§6.2.5** *Backward
sequence skip* (all three `[TITLE-ONLY]`) contemplate them — and **Figure 2 is itself a cycle** (§2).
**There is currently no rule, and that is a live hole, not a deferral:**

- §2 only catches a loop that removes *every* initial step. A backward link like `S3 → S2` leaves S1
  initial, so **it passes validation today**.
- The engine re-activating a step already in `run.done` is **unverified behaviour** — and step model
  §11 removes the timeout that used to bound a stuck run.
- **And the initial step cannot be inferred from topology once cycles exist** (§2). That is the part
  that makes this urgent rather than tidy.

> **⚠ Citation corrected 2026-08-05.** This section used to cite **"ISA-88 item 3108"** for *"looping
> back to repeat procedural elements that have previously been executed"*. **Item 3108 says nothing of
> the sort** — it reads *"– Start based on the scheduled priority of the batch;"*. The quoted text is
> **item 3112**.
>
> **And its context is weaker than the citation implied.** Items 3110-3112 sit inside a bulleted list
> of **Process Cell Management** functions: *"**Modifying any part of a control recipe that has not
> been executed.** This may include the ability to modify the procedure, such as adding and deleting
> procedural elements or looping back to repeat procedural elements that have previously been
> executed."* That is a **batch manager's recipe-editing capability**, not a statement about chart
> topology, and it says nothing about how an engine should behave when a step re-activates.
>
> The GRAFCET clause titles (§6.2.2/§6.2.4/§6.2.5) and Figure 2 are now doing all the work here.
> ISA-88 item 3112 is **corroboration at best** — do not lean on it.

**Options:** reject cycles for now (matches what the engine is proven to do, and keeps topology-
inference of the initial step valid **by construction** — but it must be journalled as *our*
restriction, since GRAFCET plainly permits them); or read `engine.py`'s `run.active`/`run.done`
handling and decide from evidence; or allow them, which means **both** shipping unverified engine
behaviour **and** adding an explicit initial-step declaration to `MasterRecipe` (§2 option (a)).

---

## 11. Open items

> ### ⛔ BLOCKING — added 2026-08-05. Settle before **unit 3**, not before unit 12.
> **(a)** Cycles, and how the initial step is determined (§2, §10) — **it may change `MasterRecipe`**.
> **(b)** OR-divergence out of a continuous step, and mixed-kind AND-convergence (§5; step model §12
> items 0b/0c). **(c)** Server-side enforcement of the initial-step cardinality (§2) — which has **no
> owning unit**, because units 9–12 are frontend and the builder is not a safety boundary.

Everything below blocks nothing.

1. **`BLOCKED ON STANDARD`** — the §5/§6 glyphs (§0). **Narrowed 2026-08-05:** Figure 2 was rendered
   directly, so the **double-border initial step** and the **transition-as-a-tick-across-the-link** are
   now seen rather than remembered (still `[DERIVED]` — Tables 1–4 remain the authority and remain
   unread). The **branch bars**, the **`=1` receptivity** and the **pit-transition cap** are still
   purely from memory.
2. **The OR exclusivity lint** (§8) — deferred deliberately; purely additive.
3. **`Not` in the condition union** — §4.3.3 makes the receptivity a boolean expression; `And`/`Or`
   without `Not` is an incomplete algebra ("advance while *not* HELD" is unwritable).
4. **The condition editor cannot author `And`/`Or` at all** *(added 2026-08-05, read directly)*.
   `views/ConditionEditor.tsx:8` declares `type CondType = 'StateReached' | 'ValueThreshold' |
   'Elapsed'`, and `:38-40` **silently falls back to `StateReached`** for anything else — so opening an
   existing compound condition and saving it **destroys it**. The engine, the wire types
   (`api/types.ts:98-99`) and `summarize()` all support compounds; only the editor does not. This bites
   §5 and §8 directly: OR branches are supposed to carry *real* distinguishing receptivities, and a
   two-clause one cannot be typed. **Belongs with unit 11.**
5. **Formula ↔ step params** — `MasterRecipe.formula` (ISA-88 §6.3.3) is dead data; `RecipeStep.params`
   are literal numbers, so a recipe cannot be scaled per batch as ISA-88 intends.
6. **Step parameters** — how the builder writes `params` and validates them against the procedure's
   *declared* parameters.
7. **The live execution view** — including how the step model's four step states render live.
