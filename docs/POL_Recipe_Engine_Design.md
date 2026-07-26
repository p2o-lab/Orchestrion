# Orchestrion — Recipe / Orchestration Engine Design (v0.2.0)

> **What this document is.** The design foundation for **v0.2.0 — the recipe/orchestration engine**,
> a sibling to `POL_and_MTP_Standards_Research.md` (the spec) and `POL_MVP_and_Architecture.md` (the
> plan). Read it before building anything in `orchestrion/recipe/` or `frontend/src/recipe/`. It
> explains **what ISA-88 / BatchML actually are**, how they map onto MTP, the engine architecture on
> top of our existing control/registry seams, the data model, and the incremental roadmap.
>
> **Status:** design locked with Marwen 2026-07-26; **not yet built.** Build proceeds increment by
> increment (M5.0 → M5.8), tested at each step (Rule 2). Journal: `docs/progress/009_m5_recipe_engine.md`.

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

An ISA-88 procedure runs like an SFC (the same construct as IEC 61131-3 SFC):
- **Step** = a phase to execute → in our world "run PEA X / service Y / procedure Z with params."
- **Transition** = the **condition** to advance ("when Reactor_A = COMPLETED", "temp > 60", "after 5 min").
- **Parallel** branch (divergence/convergence) = run steps concurrently, then wait for all (join).
- **Selection** branch = choose one path on a condition (if/else).

The "modern drag-and-drop, chart-oriented recipe builder" **is** this SFC: boxes = steps, arrows =
transitions, split lanes = parallel. We are not inventing a diagram; we are drawing the standard one.

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

**Persistence** (`db/models.py`): new **`Recipe`** table scoped to a `Project` — `id, project_id,
name, version, definition (JSON), created_at`. JSON blob + metadata columns, mirroring how `Pea`
stores its `.aml` (single source of truth, re-parsed on demand).

**API** `api/recipes.py`: recipe CRUD under a project + run control
(`POST …/recipes/{id}/run`, `…/runs/{run_id}/pause|abort`, `GET …/runs/{run_id}`) + a run WS.

**Frontend** `frontend/src/recipe/`: a **drag-and-drop chart builder** (nodes = steps → pick project
PEA/service/procedure/params; edges = transitions → pick a condition; header + formula panels) and a
**live execution view** (same chart, active step(s) highlighted from the run WS, recipe controls, the
recipe event log). React/TS/Tailwind, consistent with the existing app.

**Events** (`events.py`): add `EventKind.RECIPE` (started, step started/completed, transition fired,
completed/aborted/failed).

---

## 5. Data model (ISA-88-shaped, serialized as our JSON)

```
MasterRecipe { header: {name, version, author}, formula: {param: value}, steps[], transitions[] }
RecipeStep   { id, pea_id, service, procedure_id, params: {name: value} }        # a phase binding
Transition   { from_ids[], to_ids[], condition }                                  # SFC edge
Condition    = StateReached{pea_id, service, state}                               # e.g. COMPLETED
             | ValueThreshold{pea_id, value_name, op, threshold}                  # e.g. Temp > 60
             | Elapsed{seconds}                                                    # e.g. after 300 s
             | And[Condition...] | Or[Condition...]
```
- **Parallel** = a transition with several `to_ids`. **Join** = a transition with several `from_ids`
  (waits for all). **Selection** = two transitions out of one step with mutually-exclusive conditions.
- Example (linear then parallel), the JSON that drives both the chart and the engine:
```json
{
  "header": { "name": "Batch-42", "version": 1, "author": "Marwen" },
  "formula": { "stir_minutes": 5, "speed_rpm": 200 },
  "steps": [
    { "id": "s1",  "pea_id": 1, "service": "Stirring", "procedure_id": 1, "params": { "Duration": 300 } },
    { "id": "s2a", "pea_id": 2, "service": "Stirring", "procedure_id": 2, "params": {} },
    { "id": "s2b", "pea_id": 3, "service": "Stirring", "procedure_id": 1, "params": {} }
  ],
  "transitions": [
    { "from_ids": ["s1"], "to_ids": ["s2a", "s2b"], "condition": { "type": "StateReached", "pea_id": 1, "service": "Stirring", "state": "COMPLETED" } },
    { "from_ids": ["s2a", "s2b"], "to_ids": ["END"], "condition": { "type": "StateReached", "pea_id": 3, "service": "Stirring", "state": "COMPLETED" } }
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
