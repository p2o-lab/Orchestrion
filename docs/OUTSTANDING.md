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

- ~~**a. Run status hook + launch/abort wiring**~~ — ✅ **BUILT 2026-09-06**,
  [`progress/011`](progress/011_plant_launcher_and_endpoint_warning.md) §4. `hooks/useRun.ts`
  (polling, and it **adopts** a run already in flight) + `views/RunBar.tsx`. `Run` is blocked while
  the canvas is dirty, because it executes the *stored* definition.
- ~~**b. The live chart view**~~ — ✅ **BUILT 2026-09-06.** `ui/runView.ts` (pure, 19 tests) maps the
  report to per-step and per-transition display state; `StepNode` and `TransitionNode` render it.
  All five phases proven against a real 2-PEA stack, including `terminated` — *"finished, waiting"*.
  ⚠ **Not yet opened in a browser.** A non-editable mode was not added: Save is disabled while a run
  is live (the server 409s anyway), but the canvas is still editable underneath.
- **c. A run WebSocket, replacing the poll** — medium, and genuinely optional. `live.py` +
  `hooks/useLiveState.ts` are a close precedent for PEA state; **there is no run WS today.**
- **d. Pause/resume** — **does not exist at any layer.** See A2; it belongs with M5.6, not here.
- ~~**e. A helper to launch N VirtualPEA instances as a demo plant**~~ — ✅ **BUILT 2026-09-06**,
  [`progress/011`](progress/011_plant_launcher_and_endpoint_warning.md). `virtual_pea/plant.py`:
  `--count N` serves N modules from one process, generating a manifest per port (the endpoint lives
  *inside* the `.aml`, so N instances need N files). **Done first, not last** — HC30 declares one
  service, so without it there is nothing multi-PEA to watch and (b) would be built against a chart
  that can only hold one module. Same commit added the **duplicate-endpoint warning** on import.

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

**B1–B6 and B9 come from `010`; B7 and B8 surfaced on the 2026-08-08 end-to-end doc read** — B7 from a
conflict between two authority docs, B8 from `003`'s parked list. **None blocks M5.5.**

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

### B2 · ✅ CLOSED — the server accepted a nested `Always`

> **Fixed 2026-09-05, committed `2b9f281`.** `_check_continuous_steps_have_a_real_receptivity`
> now calls `_contains_always`, which walks the tree, so the server refuses exactly the
> charts the builder flags. The description below is what was wrong, kept for the record.
> *(The same commit exempted an **empty** recipe from the initial-step check: `ProjectView`
> creates a recipe with `steps: []` and then opens the canvas on it, so gating creation on
> "exactly one initial step" made a new recipe impossible.)*

`api/recipes.py:_check_continuous_steps_have_a_real_receptivity` tests
`isinstance(transition.condition, Always)` — a **bare** `Always` only. An `Always` **nested inside an
`Or`** is exactly as fatal, because an `Or` is true the moment any child is, and the server currently
lets it through. Now reachable from the UI, since `010` unit 11a made compounds authorable.

The builder is deliberately stricter (`containsAlways` walks the tree) so such a chart is *flagged* —
but it still saves, because the builder never blocks. **The server is the safety boundary, so that is
where this must be fixed.** Small change to one function. `010` §12, unit 12.

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

### B7 · ISA-88 citations are all draft-sourced — disclosed, not yet cross-checked

**Found 2026-08-08 while reading the docs end to end.** Every ISA-88 item number in
`POL_Step_Model_ISA88.md` — all 21 of them — comes from the **2023 Committee Draft**. Verified by
grepping both local extractions: each appears exactly once in the 2023 text and **zero times** in
**DIN EN 61512-1:2000-01**, the edition `POL_and_MTP_Standards_Research.md` §12 calls normative.

Not a mix-up: the procedural state model (Annex D, Table B.2, `RESETTING`, acting/waiting) **does not
exist in the 2000 edition** — it is new in the draft. And §12 explicitly sanctions using the draft
*"as a companion … when designing the state machine"*, which is what was done.

**The gap was disclosure**, now fixed: the step-model doc's §0 carries a SOURCE STATUS box saying a
`[CITED]` item means *"quoted from the 2023 CD"*, not *"normative ISA-88"*.

**What is still owed, and it is small:** for the handful of load-bearing concepts — the two gates
(1341), initiate + await termination (1982), acting/waiting (2382-2390) — confirm whether the
**normative 2000 text** says the same thing in its own words, or whether **`[2658-4:2022]`** (released,
and the actual contract) covers it. Then cite *that* instead. Nothing depends on this today: the wire
behaviour is 2658-4, which is released and was read directly.

### B8 · `read_mtp` never checks that `ServiceControl` is complete — a `KeyError` at subscribe

*From `003` §6.3's parked list; not tracked anywhere else until 2026-08-08.*

The parser does **not** verify that Table 13's mandatory `ServiceControl` attributes are present. An
`.aml` missing `StateCur` parses cleanly and then **`KeyError`s at subscribe time**, far from the
cause. Parked deliberately at the time (user, 2026-07-17) on the grounds that it is *"a crash, not a
silent wrong answer"* — which is the right call on severity, and still leaves a bad diagnosis.

Closing it needs Table 13 read for **mandatory vs optional**, which has not been done. *(The same
parked list also notes Blatt 5.1 Table 32's `MaxSessions` cap is unimplemented in the VirtualPEA —
minor, and only affects the test server.)*

### B9 · `update_recipe` does not bump `version`

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
- **`Not` in the condition union** (`010` §12, unit 11a). Its absence means `[IEC 60848:2013]`
  §6.2.3 EXAMPLE 2 — priority expressed as `a` versus `ā·b`, *the standard's own worked example* —
  **cannot be written in our editor.** Adding it is a wire-format change: `api/types.ts`, the
  Pydantic union, and `recipe/conditions.py`'s evaluator. Deferred, not forgotten.
- **Cycles are rejected**, though GRAFCET permits them (§6.2.2). A deliberate ISA-88 narrowing —
  item 1339 describes steps *"in series, in parallel, or a combination of both"* and never a loop.
  Chart §0a: GRAFCET is a borrowed notation, ISA-88 is the conformance target. Not a bug.
- **A branch may only end on a *pit transition***, never a *pit step*, though `[IEC 60848:2013]`
  §6.3.2 allows the latter. One terminal shape keeps `graphToTransitions` total. Chart §3.

---

## C2. Deferred from v0.1.0 — still open, and most need a real PEA

*Added 2026-08-08 on the second doc sweep. **The first version of this file missed these entirely** —
they were recorded in `progress/007` and `008`'s close-out and in the index's 007 row, but not carried
forward here. They are not recipe work, which is why they slipped.*

- **Config-parameter writing** — controlled value assignment (`[2658-4:2022]` §8.1.3) at **service**
  scope, for all four types. `control.set_parameter` exists for *procedure* parameters and would be
  generalised. **Needs a real PEA to test** — HC30 exposes none.
- **Report values + the freeze rule** (§6.2.5) — live during `EXECUTE`, **frozen** at
  Completed/Aborted/Stopped. Parsed and modelled; the freeze behaviour has never been exercised,
  because no PEA we can reach declares report values.
- **Bin / String procedure parameters** — only the **analog** kind is modelled, since HC30 has only
  analog. The parser and UI would both need the other three.
- **🔒 VQC / WQC quality codes — genuinely `BLOCKED ON STANDARD`.** The byte enumeration **is not in any
  published part**: Blatt 3 Table 7 defers it and only `0xFF` (*"no QC available"*) is defined. Writing
  `ProcessValueIn` writes `V` only, which is **correct** until the enumeration exists. This is the one
  item on this page that cannot be closed by us — it needs the standard to say something.
- **A fuller test PEA** — HC30 only exercises PEA-wide process values, so the three items above have no
  test target at all. Same root cause as [D1](#d1--the-real-pea-end-to-end-demo-owed-since-v010), and
  **do not fabricate them in the VirtualPEA** — it mirrors HC30 exactly, on purpose.

### Parked at M1, still parked — from `002` §11's close-out

*Also missed by the first version of this file.* Each was parked **with its clause**, so none needs
re-deriving — `002` §11 lists them and `parser.py` carries the citations at the sites concerned.

- **CAEX 2.15 / manifest 1.0.0 tolerance** — `caex.py:447` refuses these outright:
  *"CAEX 2.15 / manifest 1.0.0 files are not supported yet."* Deliberate (plan §8: one version behind a
  seam, never both in one unit), and the **MTPPy artifact is kept precisely as the regression fixture**
  for when it is built. **The largest item in this list.**
- **`ObjectItem` / `MethodItem`** (`[2658-1:2022]` T37 #17/#18) — `parser.py:257` records that §9.1
  leaves them **abstract**, to be *"introduced in further standard parts"*. Only `DataItem`/`OPCUAItem`
  is bound. Blocked as much by the standard as by us.
- **`Classification` / IRDI** (Table 36 #4d) — noted at `parser.py:595`, not parsed.
- **§12 runtime type/version verification** — the **MTP half is on `Pea`** (`manufacturer_uri`,
  `product_code`, `device_revision`, cited at `model.py:244`); the **runtime half is never compared**.
  ⚠ And `002` §9.3c already proved **§12.3 cannot pass against HC30**, whose `DeviceRevision` is
  literally `"No Information"` — so this needs a real PEA too.
- **HMI aspect / auto-generated faceplates** (Blatt 2) — a v2 item in `POL_MVP_and_Architecture.md` §2,
  which also records *why* it cannot precede M2: symbols reach live data via `RefID` → DataAssembly.
- **Plant topology (ports / connections)** — deferred at M2 with a seam already in place: `004` §4 notes
  the schema hangs everything off `project_id`/`pea_id`, so a `Connection`/`Port` table attaches without
  disturbing projects or PEAs. Named again in `005` §6 and `006`'s NEXT. Recipes were the other half of
  that deferral and are now built; **topology is the half still outstanding.**
- **Alarm management** (Blatt 6/7, both drafts) — a v2 item, untouched.

---

## D. Not verified — known unknowns

The honest list of what has *not* been checked, as distinct from what has been checked and found
wanting. `010` §14's audit was deliberately scoped to the recipe path.

### D1 · The real-PEA end-to-end demo (owed since v0.1.0)

**Everything is validated against the VirtualPEA and unit tests only.** M4 Step 6 — the end-to-end
demo against **VisionForge**, the lab's real PEA — has never been run, because its shipped `.aml` is
MTPPy-generated and malformed and no valid MTP for it exists yet.

*Deliberately parked 2026-08-08 — "still very far in the future."* Recorded here because the
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

### D4 · Three `[TITLE-ONLY]` tags in the chart doc are now readable but unread

`POL_Recipe_Chart_GRAFCET.md` still tags three claims `[TITLE-ONLY]` — §4.5.2 *Initial situation*,
§6.2.2 *Cycle of a single sequence*, and the step-skip / backward-skip clauses (§10). They were
written when only a 15-page preview existed. **The full text is now in `../standards/`**, so they are
no longer *unavailable* — merely *unread*. *(The §6.2.x structure table in chart §5 was the fourth;
it was read and upgraded to `[CITED]` on 2026-08-08.)*

None is load-bearing for anything built. But Rule 1 says **do not upgrade a tag without reading the
source**, so they stay as they are until someone opens those clauses. Cheap to close; worth doing
next time the chart doc is open anyway.

### D5 · Frontend lint has 10 pre-existing problems

9 errors + 1 warning, in `workspace.tsx`, `PeaView.tsx` and others — `react-hooks/set-state-in-effect`
and `react-refresh/only-export-components`. **Predate all of `010`** (verified by linting a stashed
tree), so no unit added to them. Not addressed either. Worth a small dedicated pass, mostly so the
number stops being noise that hides a real regression.

---

## E. Documentation state

**Swept 2026-08-08 — three passes, then a read-only verification.** The first pass was grep-based and
**missed the worst items**: both authority docs opened with *"Nothing here is implemented yet"*, and
the index still told every new session that IEC 60848 was not in `../standards/`. The second read the
live docs; the third read the journals too, and only then did the invented **OR rail** turn up in an
ASCII diagram that three earlier passes had scrolled past. If you need to know whether a doc is
current, **read it** — pattern-matching does not find a sentence nobody thought to search for, and it
never finds a picture.

What a reader should know:

- **[`progress/000_INDEX.md`](progress/000_INDEX.md)** — the status file and session entry point.
  Current.
- **[`progress/010_…`](progress/010_m5_step_model_correction.md)** — complete. §11/§13 are the two
  audit passes, §14 the backend audit, **§15 the deadlock decision**.
- **[`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md)** — the chart authority. §0 carries
  the **edition-mapping table**: Ed. 2.0 §6.1.x ↔ Ed. 3.0 §6.2.x, Ed. 2.0 §6.2.x ↔ Ed. 3.0 §6.3.x,
  Tables 1–11 alike in both. **Never carry a 60848 clause number between editions unchecked.**
- **[`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md)** — what a step is and how it executes. **Read
  its §0 SOURCE STATUS box before citing anything from it**: all 21 ISA-88 item numbers are from the
  2023 Committee Draft, not the normative edition (B7). Its §13 is a *historical* table of what the
  code used to contradict — not a to-do list.
- **[`POL_Recipe_Engine_Design.md`](POL_Recipe_Engine_Design.md)** — **partially superseded**, and it
  says so at the top: §2.5's chart model is wrong. Still the authority for *why*, the ISA-88/BatchML
  primer, the architecture seams and the data model. Its §6 roadmap is superseded from M5.4 on.
- **[`POL_MVP_and_Architecture.md`](POL_MVP_and_Architecture.md)** — the v0.1.0 plan of record. §6's
  file tree **was extended for `recipe/` on 2026-08-08** and is current. **§9 "Next action" is frozen
  at 2026-07-19 and still says "Next: M4"** — it now carries a banner saying so. Do not read §9, §2 or
  §7 for status; they are the original plan.
- **[`POL_and_MTP_Standards_Research.md`](POL_and_MTP_Standards_Research.md)** — the spec. Read end to
  end 2026-08-08, **no staleness found** — it is the best-maintained document in the repo, with dated
  inline corrections throughout. Note §3.3/§12: it names **DIN EN 61512-1:2000-01** as the normative
  ISA-88 and the 2023 document as a draft with *"no normative force"* — the constraint behind B7.
