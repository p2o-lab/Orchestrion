# Orchestrion — The Recipe Chart (GRAFCET / IEC 60848)

**Status: DESIGN AUTHORITY for the recipe builder chart.**
Written 2026-08-04. Supersedes §2.5 of [`POL_Recipe_Engine_Design.md`](POL_Recipe_Engine_Design.md)
("boxes = steps, arrows = transitions" — **wrong**, see §1) and the AND/OR bar-node work in
[`progress/009`](progress/009_m5_recipe_engine.md). Rationale and build order:
[`progress/010`](progress/010_m5_step_model_correction.md).

> **✅ IMPLEMENTED — [`progress/010`](progress/010_m5_step_model_correction.md) is complete
> (2026-08-08), units 9–12.** The builder now follows this document: two node kinds, the receptivity on
> the transition, the initial step inferred, a branch ending on an unwired output, synchronization bars
> drawn from link multiplicity, compound receptivities authorable, branch actions, visible OR priority
> and chart validation. *(This line used to read "Nothing here is implemented yet. The current builder
> contradicts this document." Corrected 2026-08-08.)* What is left: [`OUTSTANDING.md`](OUTSTANDING.md).

Read [`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md) first — the chart's semantics depend on it.

---

## 0. What we hold of IEC 60848, and the tags

### ✅ We hold the whole standard — both editions (2026-08-08)

- **`../standards/IEC 60848_2013/` — DIN EN 60848:2014-12**, the German adoption of **EN/IEC 60848:2013
  (Ed. 3.0)**. 57 pages, **complete**: Clause 5's symbol Tables 1–11, all of Clause 6, Clause 7 and the
  annexes. **This is the governing edition** and the one this document cites by default.
- **IEC 60848:2002 (Ed. 2.0)** — 110 pages, bilingual FR/EN, freely hosted. A useful cross-check: it
  **agrees with Ed. 3.0 on every symbol we depend on**, checked clause by clause, and its English is
  quoted here where it reads more clearly than the German.

Both are extracted to the session scratchpad. **Treat them exactly like `../standards/`: scratchpad
only, never the repo.**

> **⚠ The editions renumber Clause 6. Tables keep their numbers.**
>
> | topic | Ed. 3.0 (2013) — **cite this** | Ed. 2.0 (2002) |
> |---|---|---|
> | Selection of sequences | **§6.2.3** | §6.1.3 |
> | Activation of parallel sequences | **§6.2.6** | §6.1.6 |
> | Synchronization of sequences | **§6.2.7** | §6.1.7 |
> | End of a sequence by a pit transition | **§6.3.4** | §6.2.4 |
> | *(what Ed. 2.0 calls §6.2.2)* | §6.3.2 | **"End of a sequence by a pit step"** — a different subject from Ed. 3.0's §6.2.2 |
>
> Ed. 3.0 inserted a §6.1 *"General"*, pushing Ed. 2.0's §6.1.x → §6.2.x and §6.2.x → §6.3.x. Tables
> 1–11 are numbered and titled alike in both. **Never carry a clause number between editions
> unchecked.**

> ### 🗄 How we got here (historical)
> Until 2026-08-08 this section read *"what we **actually hold** is the official public preview"* — 15
> PDF pages, standard pages 8–13, with §5's symbol tables and all of §6 present **as table-of-contents
> titles only, not one word of their text**. Every glyph in this document was therefore either drawn
> from Figure 2 or admitted to be memory, and §6 was a wall of `[TITLE-ONLY]` tags.
>
> That preview is why the **OR rail** shipped: "how a branch is drawn" *looked* like our design freedom
> because the clause that names it was unreadable. It was not. Obtaining the full text deleted the
> symbol and upgraded four others to `[CITED]` — the detail is in the ✅ box below and in `010` §12
> (the build log; the unit-10 rebuild entry).

> **ISA-88 citations here are mixed — check which edition before reusing one.** §0a quotes the
> **normative** DIN EN 61512-1:2000-01 and says so. Everywhere else, an ISA-88 **item number**
> (1337-1339, 2391-2393, …) is from the **2023 Committee Draft**, which has *no normative force* — the
> numbering does not exist in the 2000 text. See the SOURCE STATUS box in
> [`POL_Step_Model_ISA88.md`](POL_Step_Model_ISA88.md) §0 for the full account and what to cite instead.

| tag | meaning |
|---|---|
| **`[CITED]`** | the clause text is quoted. Verifiable directly. |
| **`[TITLE-ONLY]`** | clause **number and name only**; meaning inferred *from its title*. **A guess wearing a clause number.** |
| **`[SEARCHED]`** | secondary sources agreeing with each other; the clause itself is unread. |
| **`[DERIVED]`** | inference *from* cited clauses. |
| **`[OURS]`** | a judgement call with no standard behind it. |

> ### ✅ `BLOCKED ON STANDARD — CLOSED 2026-08-08`
> This document carried a `BLOCKED ON STANDARD` box for §5's symbol tables from the day it was written.
> **It is lifted**: the tables are read, in both editions (see above). The document's pre-existing
> §6.2.3/§6.3.4 references turned out to be Ed. 3.0 numbering and were correct all along.
>
> ⚠ **Three `[TITLE-ONLY]` tags survive** — §4.5.2 *Initial situation* (§2), §6.2.2 *Cycle of a single
> sequence* (§2, §10), and the step-skip / backward-skip clauses (§10). *(A fourth — the §6.2.x
> structure rows in §5 — **was** read on 2026-08-08 and is now `[CITED]`.)*
> **They are no longer *unavailable*, only *unread*:** the text is in the scratchpad extraction and any
> of them can be upgraded by opening the clause. None is load-bearing for what is built — but per Rule 1
> **do not upgrade a tag without reading the source**, so they stay `[TITLE-ONLY]` until someone does.
> Tracked in [`OUTSTANDING.md`](OUTSTANDING.md) D4.
>
> | glyph | status after the read |
> |---|---|
> | **synchronization bar = two parallel horizontal lines, owned by the transition** | **`[CITED]`** — Table 2 **[9]**, *identical wording in both editions*; see §6 |
> | **a selection (OR) has no symbol at all** | **`[CITED]`** — §6.2.3; **the single "OR rail" was invented and is deleted** |
> | **pit transition = a transition with no succeeding step** | **`[CITED]`** — §6.3.4, which uses the term *"pit transition"* / *"Schlusstransition"* itself; see §3 |
> | **transition = a line perpendicular to the link** | **`[CITED]`** — Table 2 **[7]** |
> | **links horizontal/vertical, top→bottom, arrows required otherwise** | **`[CITED]`** — Table 3 **[10]**, **[11]** |
> | **how a receptivity is *drawn*** | **explicitly out of scope** — Ed. 3.0 adds Table 2 [7] NOTE 4, *"Die Symbolik von Transitionen ist nicht Gegenstand dieser Norm"* (the symbolism of transitions is not the subject of this standard; they may be given textually, as boolean expressions, as logic diagrams…). **New in Ed. 3.0** — Ed. 2.0 has only three notes here. Our label-beside-the-tick rendering is therefore permitted by omission, not merely `[OURS]`. |
> | **double-border initial step** | **`[SEARCHED]`** — Table 1 **[3]** names the symbol (*"dieser Schritt ist Teil der Anfangssituation"*) in **both** editions but describes it in neither; the glyph is a figure the extractor cannot render and `pdftoppm` is unavailable. Grepping *"double"* across all 110 pages of Ed. 2.0 finds only the **forcing order**'s double rectangle. Standard practice, not a quotable line. |
> | `=1` receptivity · pit-transition **cap** styling | **`[OURS]`** — the *concepts* are cited; these particular renderings are our UI affordances |

---

## 0a. GRAFCET is a borrowed notation. **ISA-88 is the conformance target.**

**Added 2026-08-06**, and it changes how every other section should be read.

This document — and `POL_Recipe_Engine_Design.md` §2.5 before it — has been written as though the
recipe chart *is* GRAFCET, on the strength of "IEC 61512-1 normatively references IEC 60848". Checked
properly, that reference is far thinner than the framing implied:

**`[CITED]`** IEC 60848 *is* listed in ISA-88 clause 2 **Normative references** — but the only statement
about what it is *for* is an informative note:

> *"NOTE 2 — Structures defined in IEC 60848 **may be useful** in the definition of procedural control
> and, in particular, in the definition of **a phase**."*
> (normative 2000 edition, DE: *"können … hilfreich sein"*)

**`[CITED]`** and the normative **DIN EN 61512-1:2000-01 §5.1.2.4** is more specific still:

> *"Die Schritte und Übergänge, wie sie in der IEC 60848 beschrieben sind, dokumentieren eine Methode,
> um **Unterteilungen einer Funktion** zu definieren."*
> — steps and transitions per IEC 60848 document a method for defining **subdivisions of a phase**.
> *(This sentence exists in the 2000 normative text; the 2023 CD dropped it, keeping only NOTE 2.)*

**A phase is a PEA service.** Its internals run on the PEA and are the vendor's business — we never
author them. **So ISA-88 points at GRAFCET for a level this project does not model at all.** Our chart
sits *above* the phase, at procedure/operation level, sequencing services across PEAs.

**What follows from this:**

| | |
|---|---|
| **binding** | ISA-88 / IEC 61512-1 — the procedural control model, items 1337-1341, the state model |
| **borrowed** | IEC 60848 — its vocabulary (step, transition, receptivity, directed link) and its drawing conventions, because they are precise, well-known and fit |
| **not binding** | GRAFCET *conformance*. Where GRAFCET is looser than ISA-88 (several initial steps, cycles), **ISA-88 wins.** Where GRAFCET is silent, we decide. |

This is why §2 can reject cycles and require exactly one initial step without apology, and why §5's
continuous-step branch rules are ours to define. **We are not claiming to emit a conformant grafcet
chart, and no part of this document should be defended as though we were.**

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
>   `RecipeStep`) — costs a backend change; or
> - **(b)** we forbid cycles, and topology-inference stays valid **by construction**.

### ✅ DECIDED 2026-08-06 — **(b): cycles are rejected; the initial step stays inferred**

And the justification is **stronger than "our restriction"**, which is how the option was framed above.
Verified against ISA-88 the same day:

- **`[CITED]` item 1337-1339** — *"A procedure is a specification of a sequence of steps… with **a
  defined beginning and end**… A procedure consists of a set of steps **in series, in parallel, or a
  combination of both**."* Series and parallel. **That is the whole list.**
- **`[CITED]`** the document was searched end to end for loop / repeat / iterate. The **only**
  "looping back" is **item 3112**, the Process Cell Management *recipe-editing* capability already
  discredited in §10. Item 2384's *"repeated execution of processing steps"* describes what happens
  **inside** an acting state, not recipe structure.

So a loop is not something we are giving up from ISA-88 — **ISA-88's procedure model never had one.**

**⚠ Stated precisely, because the difference matters:** ISA-88 does not *forbid* loops, it simply never
describes one. The honest claim is **"rejecting cycles is consistent with ISA-88, and allowing them is
unsupported by it"** — not "ISA-88 prohibits loops."

### The single initial step upgrades from `[OURS]` to `[CITED]`

**`[CITED]` item 1337** — *"a defined beginning and end."* **Singular.** So *"exactly one initial
step"* is no longer the safety-narrowing this section called it two paragraphs above; it is what the
procedure model says. Zero initial steps and several initial steps are both hard errors, on the
standard's authority.

**`[CITED]` Exactly one initial step is required** — ISA-88 item 1337's *"a defined beginning"*, above.
*(Tag upgraded from `[OURS]` on 2026-08-06.)* GRAFCET is looser — §3.1.7's *situation* is a set of
active steps (plural) and §4.2 says *"several steps may be active simultaneously"* — but **ISA-88 is
our conformance target and GRAFCET is a borrowed notation** (§0a), so the tighter rule governs.

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

**Upgraded `[TITLE-ONLY]` → `[CITED]` on 2026-08-08.** The clause text is now in hand — **§6.3.4**, and
it says precisely what the title promised. [IEC 60848:2002] §6.2.4, the same clause one edition back,
in English:

> ***"End of a sequence by a pit transition.** A pit transition is a transition, which has **no
> succeeding step**.*
> *NOTE 1 — When the pit transition is enabled and when its associated transition-condition is true,
> **the only consequence of the clearing of the transition is the deactivation of the upstream
> steps**."*

[DIN EN 60848:2014-12] §6.3.4 carries it unchanged: *"Eine Schlusstransition ist eine Transition ohne
nachfolgenden Schritt. … hat das Auslösen der Transition **allein die Deaktivierung vorgeschalteter
Schritte** zur Folge."*

Both halves of our design land on the clause: a branch ends at a **transition with no successor**, and
firing it does nothing but **deactivate its from-steps** — which is exactly what `_fire` does when
`to_ids` is empty. Even the name is the standard's own; `isPitTransition` was not our coinage after
all. The sibling clause **§6.2.2** *"End of a sequence by a **pit step**"* (a step with no succeeding
transition) is GRAFCET's other terminal, which our model does not offer — every branch of ours ends on
a transition. That is a deliberate narrowing, not an oversight: ISA-88 item 1337's *"defined beginning
and end"* is satisfied either way, and one terminal shape keeps `graphToTransitions` total.
*(§6.2.2 in Ed. 2.0's numbering — see the edition table in §0.)*

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

**`[OURS]` A transition with a *continuous* step anywhere in its `from_ids` must NOT carry `Always`** —
that would start the service and immediately complete it. For a continuous step the receptivity **is**
the completion criterion (step model §2), so a real one is required: a duration, a threshold, an
operator confirmation.

> **⚠ Scope widened 2026-08-06.** This rule used to say *"a transition **leaving** a continuous step"*,
> which reads as a step's single outgoing transition. §5(b) now lets a continuous step feed an
> **AND-join**, and that join is exactly where `=1` was going to be the default — so the rule has to be
> stated over the **transition's whole `from_ids`**, not over one step's exit. Same rule, wider net.

Two things this needs:

- **The builder must know which kind a procedure is.** It already can — `is_self_completing` is on the
  procedure schema (`api/schemas.py:81`, populated at `:140`). No new endpoint.
- **Enforced server-side too, not only in the UI.** A recipe can be `POST`ed straight to the API,
  bypassing the builder — which is exactly how the integration test works. Belongs beside the existing
  checks in `api/recipes.py:111` (`_validate_against_project`), which already resolves each step's PEA
  and service.

---

## 5. AND and OR are drawn, not placed

> **📖 Read §5 and §8 as *reasoning*, not as a description of current code.** Both were written before
> `010` and describe the engine **as it then was** — so phrases like *"currently makes the author
> hand-write `And[…]`"*, *"every branch currently carries the same default"*, *"must be restated"* and
> *"**Today** only one branch fires by accident"* are all **historical**. Every one of them was fixed:
> the two gates (unit 3), the `Always` rule over the whole `from_ids` (units 5/7b), and deliberate OR
> arbitration (unit 8). They are kept because *why* the design is what it is only makes sense against
> what it replaced. **For what the code does now, see `010` §12.**

**`[CITED]`** §4.3.2 — **re-verified verbatim 2026-08-05**: *"Directed link (definition: 3.1.2, symbol
10). A directed link connects **one or several steps to a transition, or a transition to one or
several steps**."* Corroborated by §4.2: a transition is *"characterized by: • its **preceding steps**,
• its **succeeding steps**, • its associated transition-condition"* — plural on both sides.

**The bars are how you *draw* an element with more than one link on a side — never a node.**
The "never a node" conclusion is **`[CITED]`**: it follows from §4.3.2 and §4.3.3's closed enumeration
(*"the structure comprises the following basic items"* / *"the following elements are used for the
interpretation"*), both read in full. *(This line said "§3.1's closed element list" until 2026-08-05;
§3.1 is a glossary — see §1.)*

**Upgraded `[TITLE-ONLY]` → `[CITED]` on 2026-08-08** — the clauses have been read, in both editions.
This used to say *"every §6.2.x row below — clause names, not text"*. The text confirms all four rows:

> **§6.2.6** *Activation of parallel sequences* — *"In dieser Struktur wird das Synchronisierungssymbol
> Nr. [9] angewendet, um die **gleichzeitige Aktivität mehrerer Ablaufketten durch einen oder mehrere
> Schritte** anzuzeigen."*
>
> **§6.2.7** *Synchronization of sequences* — *"The synchronisation symbol 9 is used in this structure
> to indicate the delay before preceding sequences end before the activation of the succeeding
> sequence. NOTE — **The transition is only enabled when all the preceding steps are active**."*
>
> **§6.2.3** *Selection of sequences* — *"This structure is represented by **as many simultaneously
> enabled transitions as possible evolutions**."* (no symbol — see §6)
>
> **§6.2.8** *Synchronization and activation of parallel sequences* — *"Das Synchronisierungssymbol
> Nr. [9] wird in dieser Struktur **zweimal** angewendet."*

§6.2.7's NOTE is the important one: **"only enabled when all the preceding steps are active"** is the
AND-join semantics our engine implements, now cited rather than derived.

| clause (`[CITED]`, quoted above) | structure | hangs off | backend |
|---|---|---|---|
| §6.2.6 *Activation of parallel sequences* | AND divergence | **one transition**, several steps | `Transition{from:[S1], to:[S2,S3]}` |
| §6.2.7 *Synchronization of sequences* | AND convergence | several steps, **one transition** | `Transition{from:[S2,S3], to:[S4]}` |
| §6.2.3 *Selection of sequences* | OR | **one step**, several transitions | several `Transition`s sharing a `from` |
| §6.2.8 *Synchronization and activation* | both | one transition, several both sides | `Transition{from:[…], to:[…]}` |

**`[CITED]`** the backend already says exactly this — `model.py:133`: *"Several `to_ids` = a parallel
divergence; several `from_ids` = a join."* **All four forms need no backend change.**

```
   AND divergence               OR divergence  (a selection)
      ┌────┐                       ┌────┐
      │ S1 │                       │ S1 │
      └──┬─┘                       └──┬─┘
         │                      ┌─────┴─────┐   ← NO symbol here (§6.2.3)
      ───┼───  Temp>80          │           │
      ═════════  ← two      a ──┼──  ā·b ──┼──  ← one transition per branch,
       │      │    parallel     │           │     each with its OWN receptivity
     ┌─┴┐   ┌─┴┐   lines      ┌─┴┐       ┌─┴┐
     │S2│   │S3│   (Table 2   │S2│       │S3│
     └──┘   └──┘    [9])      └──┘       └──┘
   ONE transition,            ONE step,
   2 succeeding steps         2 succeeding transitions
```

> **⚠ Corrected 2026-08-08.** The right-hand figure used to draw *"← the OR rail (single)"* across the
> selection. **There is no such symbol.** §6.2.3: a selection *"is represented by as many simultaneously
> enabled transitions as possible evolutions"* — the fan-out **is** the notation. The `a` / `ā·b`
> receptivities shown are §6.2.3 EXAMPLE 2's own way of expressing priority (§8).

### The step model is what makes these work at all

- **AND convergence** — `engine.py:12-13` currently makes the author hand-write
  `And[COMPLETED(S2), COMPLETED(S3)]`, restating as a receptivity what is already structural. With the
  two gates, all from-steps completing **is** gate #1; the receptivity becomes `=1` and the `And`
  disappears.
- **OR divergence** — every branch currently carries the same default "reached COMPLETED", so all go
  true at once and the "choice" is decided by list order. **That is not a selection.** With the two
  gates, the shared part is gate #1 and each branch carries a **real** distinguishing receptivity.

### Branches involving a *continuous* step — ✅ DECIDED 2026-08-06

Both forms were undefined until now, and both remain **`[DERIVED]`** — reasoned from the two gates and
checked against ISA-88 item 1341.

> *Updated 2026-08-08: this used to say "IEC 60848 §6.2.3 is outside the preview". **The full standard
> is now held and §6.2.3 has been read** — and it does not settle these two. It says only that
> exclusive activation "is not guaranteed from the structure" and puts the duty on the designer
> (§8). So the tag stands, but now because the clause was **read and is silent**, not because it was
> unavailable.*

**`[CITED]`** the standards basis for selection at all is **item 1339-1341**: *"Transition conditions
may be inserted between any steps to **modify which steps will execute and in what order**, usually
based on equipment, process, and operator responses."*
*(⚠ `009` justified selection with "Figure 25 — selection of procedural elements". **That is a
misreading**: Figure 25 is *"Simultaneous definition/selection of procedural elements **and equipment
entities**"*, a design-workflow figure about choosing procedure and equipment together. It says nothing
about branches. Corrected 2026-08-06 — cite item 1340, never Figure 25.)*

#### (a) OR-divergence out of a continuous step — **the winning branch is latched**

```
        S1  (continuous)
         │
      ┌──┴──┐        T_a: Temp > 80     → S2
      T_a   T_b      T_b: Elapsed 10min → S3   (the timeout branch)
      │     │
      S2    S3
```

For a continuous step the receptivities on its outgoing transitions are **jointly** its completion
criterion. **The first to fire, in priority order, wins and is recorded.** We then send `COMPLETE`
**once**, await termination, and activate the recorded branch — **ignoring any other branch that goes
true in the meantime, and not re-evaluating afterwards.**

Two reasons, both load-bearing:
1. For a continuous step, *deciding to end it* and *choosing where to go* are **one decision**. The
   condition that fired is the reason we sent `COMPLETE`; taking a different branch would mean the
   reason we stopped and the path we took disagree.
2. **Re-evaluating can deadlock.** If `Temp > 80` fires, we send `COMPLETE`, and the temperature falls
   to 79 while the service is `COMPLETING` — a re-evaluating engine finds **no true branch** and the
   run hangs with the service already terminated. Latching cannot get stuck.

**`[DERIVED]` corroboration, not citation:** GRAFCET treats clearing as *event*-driven, not level-
sampled — §3.1.9 defines transient evolution as *"the clearing of several successive transitions **on
the occurrence of a single input event**"*, and §3.1.10's note as *"the possible evolution is realised
by clearing the transition."* Consistent with latching. **§4.5.3 is now readable** (the full standard
is held) but has not been opened, so this stays `[DERIVED]` — see [`OUTSTANDING.md`](OUTSTANDING.md) D4.

> **Rejected: forbidding a continuous step more than one exit.** It would outlaw
> *"stir until temperature reached **or** time out → different paths"* — which is precisely where an
> exception branch belongs.

#### (b) AND-convergence over mixed kinds — **the join's receptivity ends every continuous branch**

```
   S2 (continuous)   S3 (self-completing)
        └──────┬──────┘
               T          ← ONE receptivity, two jobs
               │
              S4
```

**The rule:** when the join's receptivity is true **and** every self-completing from-step has already
terminated → send `COMPLETE` to **each** continuous from-step → wait until **all** from-steps hold a
final state → *then* initiate the to-steps.

**This satisfies item 1341 exactly.** At the instant the next step is initiated, *"the immediate
predecessor(s)… **have completed**"* **and** *"any intervening transition conditions are true"*. It is
also not a new mechanism — it is §3's single-continuous-step shape applied over a set.

> **Rejected: forbidding mixed-kind joins.** It would outlaw an ordinary recipe — *"run the agitator
> while you dose the acid; when dosing is done, stop stirring and move on."* Agitator continuous,
> dosing timed. Banning that to save one branch of logic is the wrong trade.

**⚠ This widens the `Always` rule in §4.** That rule is currently stated over *a step's outgoing*
transition. It must be restated over the transition: **any transition with a continuous step anywhere
in its `from_ids` may not carry `Always`** — otherwise a join with `=1` starts a continuous branch and
completes it in the same instant.

---

## 6. How the bars are drawn

**Rewritten 2026-08-08**, against the symbol tables. The previous version of this section was
**half wrong** — see the correction note at the end.

**`[CITED]` Table 2 [9] — "Synchronization preceding and/or succeeding a transition"**, in the
identical words of both editions ([IEC 60848:2002], English):

> *"When several steps are connected to the same transition, the directed links from and/or to these
> steps are grouped, to succeed or precede the synchronization symbol represented by **two parallel
> horizontal lines**."*
> *NOTE — The reference for the synchronization symbol is 9.2.2.5 of ISO 5807.*

[DIN EN 60848:2014-12]: *"…dem Synchronisierungssymbol, **dargestellt durch zwei parallele horizontale
Linien**, zu folgen bzw. voranzugehen."*

So the symbol belongs to the **transition**, on whichever side carries several steps — succeeding
only (§6.2.6, activation of parallel sequences), preceding only (§6.2.7, synchronization of
sequences), or both at once (§6.2.8). It is **two lines**, always: one symbol, not a family.

**`[CITED]` A step draws nothing.** §6.2.3: *"Diese Struktur wird durch **ebenso viele gleichzeitig
freigegebene Transitionen** gekennzeichnet, **wie es mögliche Abläufe gibt**"* — Ed. 2.0's English,
*"represented by as many simultaneously enabled transitions as possible evolutions."* The fan-out of
transitions **is** the notation. GRAFCET gives a selection no glyph at all.

**Orientation `[CITED]`.** Table 3 [10] makes links horizontal or vertical; [11] fixes the convention
top→bottom and requires that *"arrows **shall** be used if this convention is not respected"*. Our
canvas runs **left→right** and draws an arrowhead on every edge (`RecipeBuilder.EDGE`,
`MarkerType.ArrowClosed`) — which is exactly the deviation [11] sanctions. The symbol stays
perpendicular to the link, so [9]'s "horizontal" lines become vertical with our flow.

**Cost:** layout-aware rendering — a transition must size its bar from where its steps sit. React Flow
gives handles, not spans, so this is real work in `recipeGraph.barSpans` + `FlowNodes.tsx`.

> **Correction, 2026-08-08.** This section previously read: *"`[OURS]` Nodes render their own bars…
> a step grows a **single rail** when several transitions leave it"*, flagged unverified against the
> §0 block. With the tables read, the AND bar is confirmed (and now `[CITED]`) but **the OR rail was
> invented** — it does not exist in IEC 60848. It shipped in unit 10 and was deleted the same week;
> `barSpans` now returns entries for transitions only. The lesson is Rule 2's, again: the glyph came
> from memory at write-time, and the `BLOCKED ON STANDARD` note recorded the risk without stopping it.

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

**Upgraded `[SEARCHED]` → `[CITED]` on 2026-08-08**, and the secondary sources turned out to
**overstate** the standard. The clause is **§6.2.3**, and this document's reference to it was right all
along — only the text was missing. [IEC 60848:2002] §6.1.3, English:

> *NOTE — Exclusive activation of a selected sequence **is not guaranteed from the structure**. The
> designer **should** ensure that the timing, logical or mechanical aspects of the transition-conditions
> are mutually exclusive.*

> **The two editions differ in force here.** [DIN EN 60848:2014-12] §6.2.3 reads *"Der Entwickler
> **muss** sicherstellen, dass die Transitionsbedingungen … untereinander exklusiv sind"* — **must**,
> where Ed. 2.0's English says **should**. Whether that is a real strengthening in Ed. 3.0 or DIN's
> translation of "should" cannot be told without the **English** Ed. 3.0, which we do not have. Treat
> the duty as **binding** — it is the stricter reading, and it is the governing edition's word.

What the secondary sources got wrong: they reported that GRAFCET *"declares the chart faulty and
indeterminate"*. It does not. It says **"should"**, places the duty on the designer, and offers two
worked examples of discharging it:

- **EXAMPLE 1** — receptivities `a·b̄` and `ā·b`: logical exclusion. *"If 'a' and 'b' are simultaneously
  true when step 5 is active, **no transition may be cleared**."* Contention resolves to **stall**, not
  to a fault.
- **EXAMPLE 2 — "Priority sequence" / "Ablauf mit Priorität."** Receptivities `a` and `ā·b`: *"In
  diesem Beispiel wird der Transition von 5 nach 6 **Priorität** eingeräumt, die ausgelöst wird, wenn
  'a' den Wert TRUE hat."* **The standard itself expresses branch priority — inside the
  receptivities**, in both editions. (The overbars are lost in text extraction; they are recoverable
  from the prose, which is why this is quoted rather than transcribed.)

- **IEC 61131-3 SFC** additionally arbitrates via **user-defined priority between branches**.
- IEC 60848 **Annex C** exists to relate the two languages.

**This narrows the gap.** Our position below is not "GRAFCET refuses and we resolve anyway" — GRAFCET
sanctions priority, it just encodes it in the receptivity rather than in the chart's structure. Ours
remains a **deviation in mechanism**, not in intent.

**`[OURS]` Adopt SFC arbitration — explicit, visible branch priority.** A step's outgoing transitions
are walked in priority order and **at most one fires**. Exactly one branch is taken; indeterminacy is
impossible.

- **Journal it as SFC arbitration, not GRAFCET conformance.** GRAFCET's own answer is that exclusivity
  is the designer's duty, expressed *in the receptivities* (§6.2.3 EXAMPLE 2); we hoist the same intent
  into the chart so it is visible and cannot be forgotten. *(Wording corrected 2026-08-08 — this line
  used to say GRAFCET calls such a chart "faulty", which the clause does not.)*
- **No model change.** `MasterRecipe.transitions` is already an ordered list — **priority *is* that
  order.** We surface what exists as a visible ①②③, instead of an invisible artefact of array position
  that reshuffles on re-save.
  > **As built (unit 11c): ▲▼ buttons on the badge, not drag.** This bullet said *"draggable"* until
  > 2026-08-08. On a canvas node, pointer-down already means *move the node* — React Flow owns that
  > gesture, so a drag-to-reorder would fight it. Buttons are equally visible and directly
  > manipulable; `nodrag` keeps them from starting a node drag. **The requirement is that priority
  > be visible and reorderable — not that it be dragged.**
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

## 10. ✅ DECIDED — backward links / loops are **rejected**

> **Settled 2026-08-06 — cycles are a validation error.** The reasoning, the ISA-88 evidence
> (item 1337's *"a defined beginning and end"*, item 1339's series-or-parallel, and the fact that the
> document's only "looping back" is item 3112's recipe-*editing* capability) and the precise limit of
> that claim are in **§2**. GRAFCET permits cycles — §6.2.2 *Cycle of a single sequence* — but per
> **§0a** GRAFCET is a borrowed notation, not our conformance target.
>
> **Consequences, all now decided rather than open:**
> - the initial step **stays inferred from topology** (`engine.py:92`), valid by construction once
>   cycles are gone — **no `MasterRecipe` change**;
> - **exactly one** initial step, enforced in the builder **and** server-side (§2);
> - the engine's re-activation of a step already in `run.done` **stays unverified, and that is fine** —
>   it is now unreachable.
>
> The rest of this section is kept for the reasoning and the citation correction.

*(Original framing, kept for the reasoning: "this must be settled before the validation rule set is
implemented." It was — see the box above.)*

GRAFCET **§6.2.2** *Cycle of a single sequence*, **§6.2.4** *Step skip* and **§6.2.5** *Backward
sequence skip* (all three `[TITLE-ONLY]`, and now readable — D4) contemplate them — and **Figure 2 is
itself a cycle** (§2).

*The three bullets below described the hole **before** it was closed. It is closed: `api/recipes.py`
rejects cycles (Kahn) and `ui/validateChart.ts` flags them while authoring. Kept for the reasoning:*

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

*(Options as they stood before the decision — **option 1 was taken**, and on stronger grounds than
"our restriction": §2 shows ISA-88's procedure model never had a loop.)* **Options:** reject cycles
(matches what the engine is proven to do, and keeps topology-inference of the initial step valid **by
construction**); or read `engine.py`'s `run.active`/`run.done` handling and decide from evidence; or
allow them, which means **both** shipping unverified engine behaviour **and** adding an explicit
initial-step declaration to `MasterRecipe` (§2 option (a)).

---

## 11. Open items

> ### ✅ RESOLVED 2026-08-06 — the three blockers are decided; **unit 3 is unblocked**
> **(a)** Cycles rejected, initial step stays inferred, exactly one — §2 and §10.
> **`MasterRecipe` does not change.**
> **(b)** OR-divergence out of a continuous step **latches the winning branch**; a mixed-kind AND-join's
> receptivity **ends every continuous from-step** — §5. Plus the `Always` rule widened to `from_ids`
> (§4).
> **(c)** Initial-step cardinality is enforced **server-side as well as in the builder** — it lands in
> **unit 7**, beside the other structural checks in `_validate_against_project`, since units 9–12 are
> frontend and the builder is not a safety boundary.

Everything below blocks nothing.

1. ~~**`BLOCKED ON STANDARD`** — the §5/§6 glyphs (§0).~~ **CLOSED 2026-08-08.** The governing edition
   is in the repo's standards folder in full (**DIN EN 60848:2014-12 = EN/IEC 60848:2013 Ed. 3.0**),
   and **IEC 60848:2002 Ed. 2.0** alongside it. Clause 5's Tables 1–11 and all of Clause 6 are read in
   both; they agree on every symbol we use. Outcome: the AND bar, the pit transition, the transition tick and the
   link conventions are `[CITED]`; **the OR rail was invented and has been deleted**; the initial
   step's double border stays `[SEARCHED]` (its glyph is a figure we cannot render). One residue,
   not blocking: the **`=1` receptivity** rendering and the **pit-transition cap** styling remain
   `[OURS]` UI affordances — and Ed. 3.0's Table 2 [7] NOTE 4 puts transition *symbolism* outside the
   standard's scope anyway (§0), so there is nothing left to conform to there.
2. **The OR exclusivity lint** (§8) — deferred deliberately; purely additive.
3. **`Not` in the condition union** — §4.3.3 makes the receptivity a boolean expression; `And`/`Or`
   without `Not` is an incomplete algebra ("advance while *not* HELD" is unwritable).
4. **The condition editor cannot author `And`/`Or` at all** *(added 2026-08-05, read directly)*.
   `views/ConditionEditor.tsx:8` declares `type CondType = 'StateReached' | 'ValueThreshold' |
   'Elapsed'`, and `:38-40` **silently falls back to `StateReached`** for anything else — so opening an
   existing compound condition and saving it **destroys it**. The engine, the wire types
   (`api/types.ts:98-99`) and `summarize()` all support compounds; only the editor does not. This bites
   §5 and §8 directly: OR branches are supposed to carry *real* distinguishing receptivities, and a
   two-clause one cannot be typed. ✅ **FIXED at `010` unit 11a** (2026-08-08) — the editor now edits
   one `Condition` tree via `ui/conditions.ts`, so every member of the union round-trips. **One piece
   remains**: there is still no `Not`, so §6.2.3 EXAMPLE 2's `ā·b` is unwritable — see
   [`OUTSTANDING.md`](OUTSTANDING.md) §C.
5. **Formula ↔ step params** — `MasterRecipe.formula` (ISA-88 §6.3.3) is dead data; `RecipeStep.params`
   are literal numbers, so a recipe cannot be scaled per batch as ISA-88 intends.
6. **Step parameters** — how the builder writes `params` and validates them against the procedure's
   *declared* parameters.
7. **The live execution view** — including how the step model's four step states render live.
