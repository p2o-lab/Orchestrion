# Orchestrion — Recipe / Orchestration Engine Design (v0.2.0)

> **What this document is.** The design foundation for **v0.2.0 — the recipe/orchestration engine**,
> a sibling to `POL_and_MTP_Standards_Research.md` (the spec) and `POL_MVP_and_Architecture.md` (the
> plan). Read it before building anything in `orchestrion/recipe/` or the frontend recipe views. It
> explains **what ISA-88 / BatchML actually are**, how they map onto MTP, the engine architecture on
> top of our existing control/registry seams, the data model, and the incremental roadmap.
>
> **Status:** design locked with Marwen 2026-07-26. **M5.0–M5.4 built, then corrected in full by
> [`progress/010`](progress/010_m5_step_model_correction.md), which is complete (2026-08-08).
> ▶ Next is M5.5, the live execution view.** Journals: `progress/009` (historical — how it was
> first built), then **`010`** (what is in the code now). What is left:
> [`OUTSTANDING.md`](OUTSTANDING.md).

> ## ⚠ PARTIALLY SUPERSEDED — 2026-08-04
>
> This document is still the authority for **why** (§1), the ISA-88/BatchML primer (§2.1–§2.4, §2.6,
> §2.7), the architecture seams (§4), the data model (§5), and BatchML (§2.7). **Two things in it are
> wrong**, corrected by two new documents that take precedence:
>
> | wrong here | corrected by |
> |---|---|
> | **§2.5** — *"boxes = steps, **arrows = transitions**, split lanes = parallel"*. A transition is a **node** carrying the receptivity, not an arrow; arrows are *directed links* and carry nothing; AND/OR are **link multiplicity**, not elements. | **[`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md)** |
> | **§4** — *"Drive a step → `start_service(...)`"*. A step is **initiate + await termination** (ISA-88 item 1982): it needs pre-flight, `RESET`, await-started, a latched final state, and — for a *continuous* procedure — an explicit `COMPLETE`, without which it **never terminates**. | **[`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md)** |
>
> Both were found by obtaining **IEC 60848:2013** (which we had never held) and re-reading IEC 61512-1.
> The consequence is a real defect: **two consecutive steps on one PEA run only the first and report
> success.** Full rationale + the 12-unit build order:
> **[`progress/010`](progress/010_m5_step_model_correction.md)**.
>
> The **§6 roadmap below is also superseded** for M5.4 onward — `010`'s build order replaces it, and
> absorbs part of M5.5 (the run endpoint). M5.5 keeps the live execution *view*; M5.6–M5.8 stand.

---

## 1. Why — the POL only "earns its name" here

The MVP spine (v0.1.0, M0–M4) controls **one service on one PEA**: import an MTP, connect, run the
2658-4 handshake, drive a procedure, watch live values, log everything. A *Process Orchestration
Layer* becomes an *orchestration* layer only when it **sequences services across PEAs according to a
recipe**. The NAMUR/ZVEI Process Orchestration position paper (2020-10) defines runtime orchestration
as "definition of **executable master recipes**, error and exception handling, and module-overarching
functionality," built on **IEC 61512 (ISA-88)** and **IEC 62264 (ISA-95)**. Research doc §5–6 agrees:
"the recipe side is where a POL earns its name." v0.2.0 builds that engine.

**Honesty flag (important, carried through the whole version):** the orchestration layer is *not yet
a finished standard*. VDI/VDE/NAMUR 2658 standardizes the **PEA interface** (services, state machine,
handshake, values — all of which we already implement). The recipe/orchestration logic is still being
developed by NAMUR/ZVEI WG 2.4.1. So we follow **ISA-88 for recipe structure** (a real, cited
standard — IEC 61512-1 PDF is at `../standards/ISA-88 (IEC-61512-1)/`), but the **MTP↔recipe binding
and the transition-condition scheme are our own reasoned design.** Every such decision is flagged in
code and journal as *design-not-dictated* — never dressed up as a clause. (Rule 1 still binds the
parts that *are* standardized: the ISA-88 procedural structure and the ISA-88/MTP state model.)

---

## 2. ISA-88 and BatchML — the primer (read this once, it explains everything)

Newcomers conflate two different things. They are separate layers:

- **ISA-88 (IEC 61512)** is a **conceptual model and vocabulary** — *not a file format*. It is the
  batch industry's agreement on **how a recipe is structured and executed**.
- **BatchML / B2MML** is an **XML file format** (free MESA schemas) that *serializes* ISA-88/ISA-95
  concepts so recipes can be **exchanged between systems** (MES/ERP ↔ POL ↔ another tool).

Analogy: ISA-88 is the **grammar** (and a few fixed keywords); your recipe is the **story** you write
in that grammar; BatchML is one **file encoding** for saving the story so other programs can read it.

### 2.1 The core idea — separate "what to do" from "the machine that does it"

ISA-88 keeps the **recipe** (instructions to make a product) strictly separate from the **equipment**
(the plant). Two parallel 4-level towers (IEC 61512-1 §4 physical model, §5 procedural control model):

```
 EQUIPMENT (physical model)          PROCEDURE (procedural control model)
 Process Cell  — whole plant          Procedure       — whole recipe method
 Unit          — a reactor/tank       Unit Procedure  — what one unit does
 Equipment Module — a sub-function    Operation       — a major processing stage
 Control Module — a valve/motor       Phase           — smallest step that acts
```

Left = nouns you can touch; right = verbs you do. A recipe (right) *runs on* equipment (left). The
bottom-right element, a **phase**, is the smallest step that actually commands equipment.

### 2.2 Where MTP plugs in (the bridge)

From the NAMUR WG (research §5): **a PEA service = an ISA-88 phase (an "equipment procedural
element").** In Orchestrion:

| ISA-88 | Orchestrion / MTP |
|---|---|
| Unit / Equipment Module | a **PEA** (an imported MTP, a connected module) |
| **Phase** (atomic acting step) | a **service** (e.g. HC30 "Stirring") |
| parameterized phase variant | a **service procedure** (e.g. "Stirring/Duration") |
| **Procedure** (the arrangement of phases) | a **recipe** — steps across PEAs |

So our engine is "an ISA-88 procedure whose phases are PEA service procedures."

### 2.3 What a recipe contains (IEC 61512-1 §6.3)

Every recipe carries **four** categories of information:
1. **Header** — admin metadata (name, version, author, product ID).
2. **Formula** — the **parameters**: process inputs/outputs (how much, what temperature).
3. **Equipment requirements** — constraints on *what kind* of equipment may run it.
4. **Procedure** — the actual **sequence of steps** (the flowchart / SFC).

The UI therefore needs a header panel + a formula/parameters panel **in addition to** the chart.

### 2.4 The four recipe *types* (IEC 61512-1 §6.2) — same recipe, increasing equipment-specificity

`general → site → master → control`. General is equipment-agnostic (R&D); it gets progressively bound
to a site, then a plant/equipment class (**master recipe**), then — at runtime — to the exact modules
for one run (**control recipe**). **Orchestrion needs only two:** the **master recipe** (what you
author in the builder for your plant configuration) and the **control recipe** (the live instance the
engine executes and logs). General/site recipes are an MES/ERP concern above the POL.

### 2.5 The execution model = a Sequential Function Chart (this *is* the drag-and-drop chart)

> ### ⛔ SUPERSEDED — see [`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md)
>
> The paragraph below is **wrong in a way that produced two failed builder designs.** Corrected by
> IEC 60848:2013 §3.1 and §4.3.2, obtained 2026-08-04:
>
> - **"arrows = transitions" is wrong.** A **transition is a node** and carries the receptivity
>   (§4.3.3). Arrows are *directed links* (§3.1.2) and carry **nothing**. Putting the condition on the
>   edge is what produced the first broken builder.
> - **AND/OR are not elements.** §3.1's element list is **closed** — *step · transition ·
>   transition-condition · directed link · action*. §4.3.2: *"a directed link connects **one or several
>   steps to a transition, or a transition to one or several steps**"* — so AND/OR are **link
>   multiplicity**, drawn as bars. Modelling the bars as nodes produced the second broken builder.
> - **There is no START or END element either**, for the same reason.
>
> The correct statement: **the chart is GRAFCET (IEC 60848), which IEC 61512-1 normatively
> references.** Two node kinds — step and transition — alternating (§4.4 *"shall always be
> respected"*).

The "modern drag-and-drop, chart-oriented recipe builder" **is** a standard SFC/GRAFCET chart — we are
not inventing a diagram, we are drawing the standard one. What each element *is*, and how parallel
(§6.2.6/§6.2.7) and selection (§6.2.3) branches are formed, is defined in
[`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md).

*Original text, kept for the record:*
> An ISA-88 procedure runs like an SFC (the same construct as IEC 61131-3 SFC):
> **Step** = a phase to execute → "run PEA X / service Y / procedure Z with params."
> **Transition** = the **condition** to advance. **Parallel** branch = run steps concurrently, then
> join. **Selection** branch = choose one path on a condition. Boxes = steps, arrows = transitions,
> split lanes = parallel.

### 2.6 What ISA-88 dictates vs. what is ours (the three layers)

| Layer | Who names it | Examples |
|---|---|---|
| **Categories & rules** | **ISA-88** | *phase, operation, procedure, step, transition, formula, header* — the **kinds** of things + the SFC execution rules |
| **Recipe content** | **you / the operator** | *"Stir Reactor A", "Batch-42", "when A = COMPLETED", 5 min, 200 rpm* |
| **File tag names** | **BatchML** | XML tags `<MasterRecipe>`, `<RecipeElement>`, `<Formula>` |

ISA-88 also fixes two things **by name**: the element-type words (§2.1) and the **procedural-element
state model** — the states/commands a running step goes through (`IDLE, RUNNING, COMPLETE, HELD,
PAUSED, STOPPED, ABORTED…` / `START, STOP, HOLD, RESTART, RESET, ABORT…`).

> **We already implemented ISA-88's fixed state part.** MTP's **Table 14** state machine
> (IDLE/EXECUTE/COMPLETED/HELD/…) built in M3–M4 **is** the ISA-88 procedural-element state model with
> MTP's renamed labels — research §4.3 has the exact WG-2024 mapping (`RUNNING=EXECUTE`,
> `COMPLETE=COMPLETED`, …). The recipe engine adds only the **sequencing layer on top**, where the
> names are ours.

### 2.7 BatchML, concretely (later increment)

Same concepts as our JSON, in standardized XML: `<MasterRecipe>` with `<Formula>`/`<Parameter>`,
`<RecipeElement>` (a phase, with its equipment requirement = PEA/service/procedure), and
`<RecipeElementLink>` (the transitions). It affects **nothing** about the engine or the chart — it is
an **import/export adapter**. Buys interoperability (MES/ERP hand-down, cross-tool portability) and
regulatory recognition. Optional for *running* recipes; valuable for a *standards-clean open* POL.

---

## 3. Decisions locked (with Marwen, 2026-07-26)

1. **Scope** — ambitious *destination* (full engine: sequential + parallel + selection + exceptions +
   drag-and-drop builder + live execution view), *incremental* build (one tested increment at a time).
2. **Demo target** — run **multiple VirtualPEA instances** (many HC30 copies on different ports) as a
   multi-PEA "plant" in one Project. We do **not** add fake capabilities to the VirtualPEA; we
   instantiate the conformant server more than once (which is what a modular plant is). HC30 has one
   service ("Stirring", 2 procedures) — `test_api_peas.py` asserts `len(services) == 1` — so
   multi-instance is how we get something to orchestrate. See memory `prefer-real-pea-over-virtualpea`:
   this is *instances*, not *feature inflation*, so it respects that boundary.
3. **Recipe model vs. standard** — adopt ISA-88 *structure*; serialize as **our own JSON now**
   (drives the UI, fully ours); add a **BatchML/B2MML adapter later** (cheap because the model is
   already ISA-88-shaped).

---

## 4. Architecture — the engine sits on primitives we already have

It invents no new OPC UA or control code:

- **Drive a step** → `opcua/control.py::start_service(conn, service, procedure_id, values)` and
  `command_service(conn, service, cmd)` (already do the full §6.2.1 handshake + procedure + command,
  and return the mode `changed` list).
- **Evaluate a transition** → `opcua/registry.py::PeaRegistry.snapshot(pea_id)` → `LiveState.states`
  (service→state name) and `.values` (name→value), already streamed live.
- **Live connection** → `registry.connection(pea_id)`; **log** → `registry.record_event(...)`.

**New backend module `orchestrion/recipe/`:**
- `model.py` — ISA-88-shaped Pydantic model (see §5).
- `conditions.py` — pure `evaluate(condition, snapshots, elapsed) -> bool` (no I/O → unit-testable).
- `engine.py` — `RecipeEngine`: one async task per run; walks the step/transition graph; tracks run
  status; exposes run/pause/abort; streams run state to WS; records `EventKind.RECIPE` events.
  > *As built: run + abort + observable status, and `EventKind.RECIPE`. **No pause, no WS streaming.**
  > `010` also added `driver.py` (the `StepDriver` seam) and `runs.py` (`RunManager`), which this
  > design did not anticipate.*

**Persistence** (`db/models.py`): new **`Recipe`** table scoped to a `Project` — `id, project_id,
name, version, definition (JSON), created_at`. JSON blob + metadata columns, mirroring how `Pea`
stores its `.aml` (single source of truth, re-parsed on demand).

**API** `api/recipes.py`: recipe CRUD under a project + run control
(`POST …/recipes/{id}/run`, `…/runs/{run_id}/pause|abort`, `GET …/runs/{run_id}`) + a run WS.

> *As built (2026-08-08): CRUD, `run`, `abort`, `GET …/runs/{run_id}` and `GET …/runs` exist.
> **`pause` and the run WS do not** — see [`OUTSTANDING.md`](OUTSTANDING.md) A1. Pause is a Table 14
> command with defined semantics, so it is Rule 1 work and belongs with M5.6.*

**Frontend** — *as built, this landed in `frontend/src/views/` (`RecipeBuilder`, `StepNode`,
`FlowNodes`, `ConditionEditor`, `NodePalette`) over pure logic in `frontend/src/ui/`
(`recipeGraph.ts`, `conditions.ts`, `validateChart.ts`); there is no `src/recipe/` directory.*
A **drag-and-drop chart builder** (~~nodes = steps → pick project PEA/service/procedure/params; edges =
transitions → pick a condition~~ — **that is §2.5's superseded model**: a transition is a **node**
carrying the receptivity and edges carry nothing, see
[`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md); header + formula panels) and a
**live execution view** (same chart, active step(s) highlighted, recipe controls, the recipe event
log — **M5.5, not yet built**, and it will poll `GET …/runs/{id}` because there is no run WS).
React/TS/Tailwind, consistent with the existing app.

**Events** (`events.py`): add `EventKind.RECIPE` (started, step started/completed, transition fired,
completed/aborted/failed).

---

## 5. Data model (ISA-88-shaped, serialized as our JSON)

```
MasterRecipe { header: {name, version, author}, formula: {param: value}, steps[], transitions[] }
RecipeStep   { id, pea_id, service, procedure_id, params: {name: value} }        # a phase binding
Transition   { from_ids[], to_ids[], condition }    # a NODE carrying the receptivity, never an edge
Condition    = Always{}                                                            # `=1`, added at 010 unit 5
             | StateReached{pea_id, service, state}                               # e.g. COMPLETED
             | ValueThreshold{pea_id, value_name, op, threshold}                  # e.g. Temp > 60
             | Elapsed{seconds}                                                    # e.g. after 300 s
             | And[Condition...] | Or[Condition...]                                # min_length=1 on both
```
> *`Always` is the GRAFCET `=1` receptivity and the default for a self-completing step, where
> completion is the other gate (chart §4). It is **invalid** on a transition whose from-step is
> continuous. There is still **no `Not`** — see [`OUTSTANDING.md`](OUTSTANDING.md) §C.*
- **Parallel** = a transition with several `to_ids`. **Join** = a transition with several `from_ids`
  (waits for all). **Selection** = two transitions out of one step with mutually-exclusive conditions.
- Example (linear then parallel), the JSON that drives both the chart and the engine.
  > **⚠ Rewritten 2026-08-08 — the original taught the anti-pattern `010` removed.** Both transitions
  > used to carry `StateReached … "COMPLETED"`. Under the **two gates** (step model §3, [61512-1] item
  > 1341) completion is **gate #1 — structural**, so restating it as a receptivity is noise, and on a
  > *continuous* step it is circular. The corrected example shows both rules instead:
  > - **the split carries `Always`** (`=1`) — `s1` runs `procedure_id 2`, HC30's **self-completing**
  >   `Duration` procedure, so the step ending *is* the gate and there is nothing to add;
  > - **the join carries a real receptivity** — `s2b` runs `procedure_id 1`, the **continuous**
  >   procedure, which never ends by itself. Its receptivity **is** the completion criterion, so
  >   `Always` there would be rejected (chart §4, enforced in `api/recipes.py`); `Elapsed` gives it a
  >   real one, and firing sends `COMPLETE` to `s2b` before advancing.
  >
  > *(`s1`'s `procedure_id` also changed 1 → 2: it carried a `Duration` parameter while naming the
  > continuous procedure, which was incoherent in the original.)*
```json
{
  "header": { "name": "Batch-42", "version": 1, "author": "Marwen" },
  "formula": { "stir_minutes": 5, "speed_rpm": 200 },
  "steps": [
    { "id": "s1",  "pea_id": 1, "service": "Stirring", "procedure_id": 2, "params": { "Duration": 300 } },
    { "id": "s2a", "pea_id": 2, "service": "Stirring", "procedure_id": 2, "params": {} },
    { "id": "s2b", "pea_id": 3, "service": "Stirring", "procedure_id": 1, "params": {} }
  ],
  "transitions": [
    { "from_ids": ["s1"], "to_ids": ["s2a", "s2b"], "condition": { "type": "Always" } },
    { "from_ids": ["s2a", "s2b"], "to_ids": ["END"], "condition": { "type": "Elapsed", "seconds": 60 } }
  ]
}
```

**Control recipe / run** = a runtime instance (in-memory first, like the event log/registry): the
master bound to the project's connected PEAs, plus current active step(s), status
(`running/paused/completed/aborted/failed`), and per-step timing (for `Elapsed`). Persisting run
history is a later increment.

---

## 6. Incremental roadmap (journal `009`; each increment tested + paused for go)

- **M5.0 — ISA-88 read + recipe data model.** Rule-1 first: extract & read IEC 61512-1 (§4 physical,
  §5 procedural, §6.2 recipe types, §6.3 recipe contents, procedural-element state model) + WG-2024
  ISA-88↔MTP mapping; write the clause checklist. Build `recipe/model.py` + `Recipe` table + CRUD API.
  **Test:** a recipe round-trips through persistence; validation rejects a step referencing an unknown
  PEA/service/procedure.
- **M5.1 — sequential engine (walking skeleton).** `engine.py` + `conditions.py` for a **linear**
  recipe with `StateReached`. Run/abort. **Test:** a 2–3-step linear recipe runs end-to-end across
  **2 VirtualPEA instances**; reaches COMPLETED; events logged.
- **M5.2 — richer conditions.** `ValueThreshold`, `Elapsed`, `And/Or`. **Test:** each advances a run;
  unit tests on `conditions.evaluate`.
- **M5.3 — parallel branches.** Divergence + convergence (join waits for all). **Test:** a diamond
  recipe (split → two concurrent steps → join) across 3 PEAs.
- **M5.4 — drag-and-drop builder UI.** React chart builder + header/formula panels; author + persist.
  **Test:** build a recipe in the UI, save, run it.
- **M5.5 — live execution view.** Watch a run on the chart (active steps highlighted) over the run WS;
  run/pause/abort controls. **Test:** launch a run from the UI, watch it progress live.
- **M5.6 — exception & selection handling.** Step failure (service goes ABORTED/STOPPED unexpectedly)
  → recipe hold/abort policy; selection (if/else) branches. **Test:** force a step to fail → policy
  fires; a selection recipe takes the right branch.
- **M5.7 — recipe logging + polish.** Full `EventKind.RECIPE` timeline, run history, empty/error
  states, visual polish. **Test:** the log tells the full story of a run.
- **M5.8 — BatchML/B2MML adapter (later, optional).** Import/export the model as B2MML XML.
  **Test:** round-trip a recipe through BatchML.

---

## 7. Verification (end-to-end)

1. Launch **2–3 VirtualPEA instances** — `virtual_pea/run.py` on ports 48050/48051/48052 (a helper to
   start N at once is part of M5.1's test setup).
2. Create a Project; import the HC30 MTP once per instance (`Reactor_A/B/Blender`); connect all.
3. Author (or POST) a recipe sequencing their Stirring procedures — linear first, then parallel.
4. Run it; watch live state advance in `PeaView` + the recipe view; confirm the run reaches COMPLETED
   and the event log shows the recipe→step→transition timeline.
5. `pytest -q` stays green and grows each increment; `npm run build` clean.

---

## 8. Guardrails

- **Rule 1** — verify ISA-88 structure/state-model against the IEC 61512-1 PDF before modeling; cite
  every borrowed term; explicitly mark the MTP↔recipe binding and condition scheme as *our design*
  (the orchestration layer is not yet standardized). Never guess.
- **Rule 2** — one increment at a time, tested, journalled, paused for go before the next.
- Reuse `opcua/control.py` + `opcua/registry.py` — the engine adds orchestration logic only.
- Git stays Marwen's; one commit per increment, his dictated message.

---

## 9. Open questions / parked

- **Run-state persistence** — in-memory first (matches the event log); persist run history later.
- **Formula scaling** (batch-size normalization, §6.3) — parked; parameters are literal at first.
- **Equipment requirements → automatic PEA selection** (capability/skill matching, research §5,
  `[RWTH-POL-2025]`) — parked; steps bind to an explicit PEA at first.
- **BatchML** (M5.8) — the interoperability increment; not on the critical path to a working engine.
- **ISA-95 northbound** (MES/ERP) — out of scope for v0.2.0.
