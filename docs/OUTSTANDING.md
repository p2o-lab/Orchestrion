# Orchestrion — Outstanding Work

> **What this file is.** The standing list of everything known to be unfinished, owed, deferred or
> unverified, as of **2026-08-08**, when [`010`](progress/010_m5_step_model_correction.md) closed.
>
> **It names and explains items. It does not plan them.** No step lists, no file-by-file designs —
> the next session writes the detailed plan for whatever it picks up. Each entry says *what it is*,
> *why it matters*, and *where the detail already lives* so nothing has to be re-derived.
>
> **This is not the status file.** [`progress/000_INDEX.md`](progress/000_INDEX.md) remains the
> always-current status and the place a session starts (Rule 3). This is the backlog behind it.
>
> **Keep it honest.** An item leaves this file when it is *done*, or when it is *consciously
> dropped* — never because it got old.

---

## Where the project stands

**v0.1.0 (M0–M4) shipped and tagged.** MTP parser, OPC UA client, VirtualPEA, control handshake,
live values, event log, React HMI.

**v0.2.0 (M5, the recipe engine) is most of the way there.** M5.0–M5.3 built the engine and M5.4 the
builder; both were then found structurally wrong against IEC 60848 and ISA-88, and
[`010`](progress/010_m5_step_model_correction.md) corrected them in full — 12 units, two audit
passes, the core defect proven dead over HTTP. **264 backend + 137 frontend tests green.**

What remains is **M5.5 → M5.8**, plus the corrections `010` deliberately left behind.

---

## A. Next milestone work

### A1 · M5.5 — the live execution view ← **the next thing**

You can author and run a recipe, but you cannot **watch** one. That is the whole point of a POL, and
it is the last piece before the recipe engine is genuinely usable.

**Mostly frontend.** The backend already does its half: `POST …/recipes/{id}/run`, `GET …/runs/{id}`
(status, per-step states, latched terminal states, event trail), `GET …/runs`, and the abort
endpoint. `GET …/runs/{id}` is *truthful mid-run* — it was not before `010` §14's **P1** fix, which
would have made this view render an empty chart.

Four separable pieces, in rough size order:

- **a. Run status hook + launch/abort wiring** — small. Poll `GET …/runs/{id}`. **No backend change.**
- **b. The live chart view** — the bulk. A read-only canvas with active steps highlighted. Reuses
  `recipeToGraph` and the existing nodes; needs a run-state rendering pass and a non-editable mode.
- **c. A run WebSocket, replacing the poll** — medium, and genuinely optional. `live.py` +
  `hooks/useLiveState.ts` are a close precedent for PEA state; **there is no run WS today.**
- **d. Pause/resume** — **does not exist at any layer.** See A2; it belongs with M5.6, not here.

> **The one Rule 1 edge in an otherwise free-design milestone.** How a running step is *drawn* is
> ours — Ed. 3.0's Table 2 [7] NOTE 4 even puts transition symbolism outside IEC 60848. But the
> **state vocabulary is not ours**: the 16 states are `[2658-4]` Table 14 and acting/waiting is
> ISA-88. The view must render `state/classification.py` (built for exactly this at `010` unit 1) and
> must not invent a parallel vocabulary beside it. Cheap to get right, expensive to unpick.

### A2 · M5.6 — exception-handling policy + run-level propagation

**A full Rule 1 unit** — the most standards-bound work left in M5.

`010` unit 6 did the *engine* half: held/paused reported, a disconnect fails the run naming the PEA
and step, a raising `drive_step` fails the run instead of escaping, and abort names what it left
running. What is missing is the **policy** — what the POL actually *does* when a step fails — and
**run-level command propagation**.

Two specifics worth knowing before planning it:

- **`abort()` commands no PEA.** It sets a flag and reports what it leaves running. That is
  deliberate: `[IEC 61512-1]` items 2233-2235 say the standard *"does not specify propagation
  rules"*, so this design is **ours to make** — a rare case of the standard marking the edge of its
  own authority. A known limitation, stated rather than hidden.
- **Pause is not a UI concern.** `PAUSE` is a Table 14 command with defined semantics, and ISA-88
  distinguishes *pause* (stop at a safe point) from *hold* (an exception response). Guessing there
  is a real defect, which is why it sits here and not in M5.5.

Authority: `POL_Step_Model_ISA88.md` (the four §7.4 exception levels, items 2341-2369) and
`[2658-4]` Table 14 + `CommandEn`.

### A3 · M5.7 — run history + persistence

**Runs are in-memory only.** `RunManager._runs` lives for the process lifetime and dies with it, so
there is no history across restarts — and it is also never evicted (see B5).

One thing to settle *before* designing the schema: whether run history is meant to be a **batch
production record** in the ISA-88 sense. We hold `DIN EN 61512-1` (**Part 1 only**); records are a
later part we do **not** have. If the answer is yes, that part is needed first — cheap to ask now,
expensive to retrofit onto an invented schema.

### A4 · M5.8 — BatchML / B2MML import-export

Explicitly "later" in the M5 roadmap. **The easy kind of standards work:** B2MML/BatchML are
machine-readable schemas, freely published by MESA, and CLAUDE.md Rule 1 already lists them as an
approved source — implement from the schema, nothing to interpret. Primer already written:
`POL_Recipe_Engine_Design.md` §2.7.

---

## B. Owed corrections — real gaps, recorded not fixed

These are all from `010`. None blocks M5.5.

### B1 · 🚩 The runtime liveness check — no deadlock detection

**The chief item.** If no transition can ever fire again, the run waits for ever and still reports
`status: "running"`. Reachable **without any bug**: a step feeding an AND-join *and* another exit,
where the sibling fires first — correct arbitration that permanently strands the join.

A cheap **authoring warning** ships (`starvableJoins`, surfaced by `validateChart`), but it cannot
prove a chart will strand, cannot see a receptivity that simply never comes true, and does nothing
once a run is live. **The engine still has no way to notice a dead run.**

The full discussion — what it is, the decidable/undecidable split, the three options weighed and why
the runtime check won — is `010` **§15**, including the intended shape. Worth doing **around M5.5b**:
a stranded run is exactly what the live view will otherwise show as "running for ever" with no
explanation.

### B2 · 🚩 The server accepts a nested `Always`

`api/recipes.py:_check_continuous_steps_have_a_real_receptivity` tests
`isinstance(transition.condition, Always)` — a **bare** `Always` only. An `Always` **nested inside an
`Or`** is exactly as fatal, because an `Or` is true the moment any child is, and the server currently
lets it through. Now reachable from the UI, since `010` unit 11a made compounds authorable.

The builder is deliberately stricter (`containsAlways` walks the tree) so such a chart is *flagged* —
but it still saves, because the builder never blocks. **The server is the safety boundary, so that is
where this must be fixed.** Small change to one function. `010` §13, unit 12.

### B3 · `_fire` has no `is_connected` check

A PEA dropping between `_observe` and `_fire` surfaces as `StepBindingError: … not connected` instead
of the clear disconnect message `010` §11 designed. A worse diagnosis, not a worse outcome.

### B4 · `require_command_enabled` reads, then writes

`CommandEn` can change in between, turning a valid command into a spurious failure. **Untested
against real timing** — and it may only ever bite on real hardware, which is one more reason the
real-PEA demo (D1) matters.

### B5 · Runs are never evicted

`RunManager._runs` grows for the process lifetime. Harmless in a session, wrong in a service. Related
to A3, and probably solved by the same work.

### B6 · The engine trusts the API for acyclicity

`api/recipes.py` rejects cycles properly; the engine's own guard catches only *pure* cycles. Fine
while every recipe arrives through the API, a latent trap if anything ever constructs a run directly.

### B7 · `update_recipe` does not bump `version`

`api/recipes.py:297` does `row.version = body.header.version` — it takes whatever the client sent.
`db/models.py:69` documents that *"`version` bumps when a recipe is edited"*. **One of the two is
wrong**; which one is a design decision, not a bug report. Worth settling because recipe versioning
is exactly the kind of thing an audit trail later depends on.

---

## C. Deliberately deferred — decisions, not debt

Listed so nobody "discovers" them and re-opens a settled question.

- **The OR exclusivity lint** (chart §8). Detecting *provably* overlapping branches — identical
  conditions, `Temp>80` vs `Temp>50` on one value, two `StateReached` on one service. Deferred
  because such a chart **still runs deterministically** under our priority arbitration; it just has
  a silently dead branch. An authoring smell, not a safety problem. Purely additive whenever added.
- **`Not` in the condition union** (`010` §13, unit 11a). Its absence means `[IEC 60848:2013]`
  §6.2.3 EXAMPLE 2 — priority expressed as `a` versus `ā·b`, *the standard's own worked example* —
  **cannot be written in our editor.** Adding it is a wire-format change: `api/types.ts`, the
  Pydantic union, and `recipe/conditions.py`'s evaluator. Deferred, not forgotten.
- **Cycles are rejected**, though GRAFCET permits them (§6.2.2). A deliberate ISA-88 narrowing —
  item 1339 describes steps *"in series, in parallel, or a combination of both"* and never a loop.
  Chart §0a: GRAFCET is a borrowed notation, ISA-88 is the conformance target. Not a bug.
- **A branch may only end on a *pit transition***, never a *pit step*, though `[IEC 60848:2013]`
  §6.3.2 allows the latter. One terminal shape keeps `graphToTransitions` total. Chart §3.

---

## D. Not verified — known unknowns

The honest list of what has *not* been checked, as distinct from what has been checked and found
wanting. `010` §14's audit was deliberately scoped to the recipe path.

### D1 · The real-PEA end-to-end demo (owed since v0.1.0)

**Everything is validated against the VirtualPEA and unit tests only.** M4 Step 6 — the end-to-end
demo against **VisionForge**, the lab's real PEA — has never been run, because its shipped `.aml` is
MTPPy-generated and malformed and no valid MTP for it exists yet.

*Marwen, 2026-08-08: deliberately parked — "still very far in the future."* Recorded here because the
consequence is real: **no line of this project has been proven against real hardware timing**, and
B4 is precisely the kind of defect that only appears there. `progress/008` close-out.

### D2 · Modules not re-read in the `010` audit

`mtp/` (~1,750 lines) · `virtual_pea/` · `events.py` · `db/` · the non-recipe API modules. M1/M2 code,
unchanged since July, covered by their own suites and audited in `002`/`003`. Not suspected —
just not re-verified, which is a different claim.

### D3 · Two VirtualPEA divergences from a real PEA

Both known, neither a bug in the POL, both shaping what our tests can actually prove:

- **It never publishes `STARTING`, and publishes `EXECUTE` for one 50 ms scan** — it calls
  `_auto_advance()` before `_publish()` while the POL subscribes at 200 ms. So the POL can
  legitimately observe `IDLE → COMPLETED` with nothing between. `control.await_started` was built to
  tolerate exactly this.
- **Its self-completing procedure ignores `Duration`** — it reaches `COMPLETED` in ~100 ms, so
  `POL_Step_Model_ISA88.md` §9's worked example ("a 60 s self-completing step") **has no test
  target.**

### D4 · Frontend lint has 10 pre-existing problems

9 errors + 1 warning, in `workspace.tsx`, `PeaView.tsx` and others — `react-hooks/set-state-in-effect`
and `react-refresh/only-export-components`. **Predate all of `010`** (verified by linting a stashed
tree), so no unit added to them. Not addressed either. Worth a small dedicated pass, mostly so the
number stops being noise that hides a real regression.

---

## E. Documentation state

Swept **2026-08-08**; believed current. What a reader should know:

- **[`progress/000_INDEX.md`](progress/000_INDEX.md)** — the status file and session entry point.
  Current.
- **[`progress/010_…`](progress/010_m5_step_model_correction.md)** — complete. §11/§13 are the two
  audit passes, §14 the backend audit, **§15 the deadlock decision**.
- **[`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md)** — the chart authority. §0 carries
  the **edition-mapping table**: Ed. 2.0 §6.1.x ↔ Ed. 3.0 §6.2.x, Ed. 2.0 §6.2.x ↔ Ed. 3.0 §6.3.x,
  Tables 1–11 alike in both. **Never carry a 60848 clause number between editions unchecked.**
- **[`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md)** — what a step is and how it executes.
- **[`POL_Recipe_Engine_Design.md`](POL_Recipe_Engine_Design.md)** — **partially superseded**, and it
  says so at the top: §2.5's chart model is wrong. Still the authority for *why*, the ISA-88/BatchML
  primer, the architecture seams and the data model.
- **[`POL_MVP_and_Architecture.md`](POL_MVP_and_Architecture.md)** — the v0.1.0 plan of record. Its
  §9 "Next action" is dated 2026-07-19 and still says "Next: M4"; the section states outright that it
  is *"only the original plan of record"* and points at `000_INDEX.md`. **Left as a historical
  document on purpose** — its file tree also predates `recipe/`. Do not read it for status.
- **[`POL_and_MTP_Standards_Research.md`](POL_and_MTP_Standards_Research.md)** — the spec.
