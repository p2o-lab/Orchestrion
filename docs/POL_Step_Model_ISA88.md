# Orchestrion - The Step Model (ISA-88 + 2658-4)

**Status: DESIGN AUTHORITY for what a recipe step *is* and how it executes.**
Written 2026-08-04. Supersedes §2.5 and §4's "drive a step" of
[`POL_Recipe_Engine_Design.md`](POL_Recipe_Engine_Design.md) where they disagree.

> **IMPLEMENTED (2026-08-08).** `engine.py`, `control.py`, `state/classification.py`, `recipe/driver.py`
> and `recipe/runs.py` now follow this document, and the defect it was written to kill - two
> consecutive steps on one PEA running only the first and reporting success - is dead, proven over
> HTTP. *(This line used to read "Nothing here is implemented yet. The current `engine.py`
> contradicts this document." Corrected 2026-08-08.)*
>
> Known gaps against this document are tracked in [`OUTSTANDING.md`](OUTSTANDING.md) §B - chiefly
> that **the engine still cannot detect a deadlocked run**.

---

## 0. Sources, and the confidence tags

- `../standards/ISA-88 (IEC-61512-1)/DIN EN IEC 61512-1_2023-11-00_ML_3491810.pdf` - extracted, read.
  **Item numbers below are printed *in the PDF itself*** - it is a Committee Draft carrying line
  numbers - so they survive re-extraction and grep directly: `grep -n "[^0-9]1341 *$"`.
  *(Corrected 2026-08-05: this line used to say "the line-numbered items in that extraction", which
  implied they were an artefact of our tooling. Two independent extractions - 2026-07-28 and
  2026-08-05, different `pypdf` versions - place item 1341 at different **file** lines and both carry
  the printed number.)*
- `../standards/VDI-2658/VDI-VDE-NAMUR 2658 Blatt 4_2022-10-00_ML_3331566.pdf` - **extracted and read
  2026-08-05.** §2 no longer rests on our own docstring, and §4a below is new because of it.
- Remaining 2658-4 facts come from our parsed model, which carries the clause: `mtp/model.py:184`,
  `state/codes.py:15`/`:36`.

> ### SOURCE STATUS - every ISA-88 citation here is the **2023 draft**, not the normative edition
> *Added 2026-08-08. This document previously named its source but never flagged its status.*
>
> **Verified, not assumed.** All **21** item numbers cited in this document - 1341 · 1982 · 2233 ·
> 2235 · 2316 · 2326 · 2331 · 2341 · 2355 · 2369 · 2382 · 2388 · 3444 · 3450 · 3451 · 3452 · 3455 ·
> 3490 · 3517 · 3630 · 3640 - were grepped against **both** local extractions:
>
> | | DIN EN IEC 61512-1:**2023-11** (CD) | DIN EN 61512-1:**2000-01** (normative) |
> |---|---|---|
> | each of the 21 item numbers | **present, exactly once** | **0 - none of them exist** |
> | `Table B.2` | present | **absent** |
> | `RESETTING` | 19 | **0** |
> | Annex D / Anhang D | present | **absent** |
> | extent · language | 277 pp · EN | 60 pp · DE |
>
> **So: 100 % of this document's ISA-88 material is 2023-sourced. None of it is from the 2000 text** -
> which is not a slip, because the procedural state model *is not in the 2000 edition at all*. It is
> new in the draft, exactly as [`POL_and_MTP_Standards_Research.md`](POL_and_MTP_Standards_Research.md)
> §3.3 records (*"new Annex D procedural-state reference model"*).
>
> **This is sanctioned, and the research doc says so.** §12 directs us to use the draft's *"clause 7 +
> Annex D state models as a **companion** to `[WG-2024]` when designing the state machine"* - precisely
> this document's use. What §12 forbids is treating it as *"the valid standard"*, and that is the line
> to hold.
>
> **How to read the tags here, therefore:** a `[CITED]` on an ISA-88 item means **"quoted verbatim from
> the 2023 Committee Draft"** - *not* "normative ISA-88". Two consequences:
> 1. **Do not use an item number to defend a conformance claim.** Cite **`[2658-4:2022]`** instead - it
> is *released*, it is what the PEA actually implements, and on the points that matter here (the 16
> states, `Complete` for continuous procedures, `CommandEn`, the handshake) it says the same thing
> with real force.
> 2. **Item numbers may move** if Ed. 2.0 changes before publication. The quoted *text* is what to
> re-verify against, never the number alone.
>
> **Nothing built rests on this being normative.** The wire behaviour - what the POL writes, when - is
> `[2658-4:2022]`, released and read directly. ISA-88 supplies the concepts (initiate + await
> termination, the two gates, acting/waiting, the four exception levels); 2658-4 supplies the contract.
> Tracked in [`OUTSTANDING.md`](OUTSTANDING.md) B7.

> ### Audit - 2026-08-05
> Every `[CITED]` claim here was re-checked against the primary sources. Most verified verbatim.
> **§1 was false**, **§2's diagram contradicted §5**, and **a 2658-4 obligation was missing entirely**
> (now §4a). All are corrected below.

Every claim is tagged, so a reader can tell a quoted clause from an inference at a glance.

| tag | meaning |
|---|---|
| **`[CITED]`** | the clause text is quoted. Verifiable against the PDF or the source line directly. |
| **`[TITLE-ONLY]`** | clause **number and name only**; the meaning is inferred from the title and the clause text is unread. |
| **`[SEARCHED]`** | secondary sources agreeing with each other; the clause itself is unread. |
| **`[DERIVED]`** | inference *from* cited clauses, rather than a quotation. |
| **`[OURS]`** | a judgement call with no standard behind it. Design-not-dictated. |

**Do not upgrade a tag without reading the source.** If implementation makes a `[TITLE-ONLY]` or
`[DERIVED]` line load-bearing, stop and say `BLOCKED ON STANDARD`.

---

## 1. A step is "initiate + await termination"

**`[CITED]`** §6.5 item 1982: *"each step defined within a procedural element consists of **initiating
and awaiting termination** of one subordinate procedure."* Two verbs. There is no third.

**`[CITED]`** items 3444-3451: one execution runs from IDLE → STARTING/RUNNING *"until it eventually
transitions to a final waiting state that indicates either normal completion (COMPLETE) or abnormal
termination (STOPPED or ABORTED). … **Upon this procedural element reaching a final state**, the
higher level procedural element … **may progress its own operating sequence to the next step**."*

**`[CITED]`** A PEA service **is** an ISA-88 procedural element. But MTP's 16 states and the Reference
Procedural State Model are **not a state-for-state match**: MTP **drops four**, **adds one**, and
**renames two**.

> **Corrected 2026-08-05.** This paragraph used to read *"matches the Reference Procedural State
> Model state for state; only RUNNING ↔ `EXECUTE` differs in name"*, tagged `[CITED]`. **That was
> false** - a paraphrase wearing a clause number, which is exactly the failure Rule 1 exists to catch.
> Measured against Table B.2 and Table 14, both read in full:
>
> | | |
> |---|---|
> | **dropped** - in ISA-88, absent from Table 14 | `SUSPENDING` · `SUSPENDED` · `UNSUSPENDING` · `CLEARING` |
> | **added** - in Table 14, absent from ISA-88 | `RESUMING`. `grep -c RESUMING` over the extraction → **0**. Item 3497-3498 sends `RESUME` from `PAUSED` **straight to** `RUNNING`, and Table B.2's PAUSED row reads *"Waits for a RESUME command before returning to RUNNING"* - there is no intermediate state |
> | **renamed** | `RUNNING` → `EXECUTE` · `COMPLETE` → `COMPLETED` |
>
> *(The four dropped states are why research §4.3 records the WG's advice to use MTP's PAUSING loop
> "not ISA-88 SUSPENDING", and why `CLEARING` never appears in our code.)*
>
> Our own research doc §4.3 already recorded this (the WG-2024 table marks `Restart` and `Complete`
> *Not Used* in ISA-88, and recommends the PAUSING loop *"not ISA-88 SUSPENDING"*) - the error was
> introduced here, not inherited.
>
> **No decision in this document changes.** §6 applies ISA-88's *acting/waiting test* (items
> 2382-2390) to MTP's own 16 states; it never needed the two models to be identical. Only the
> justifying sentence was wrong.

**`[CITED]`** items 3490-3517 - in ISA-88's model the POL sends **`START` and `RESET`**; everything
between is an `SC` transition ("State Change as a result of state actions completed") the PEA performs
itself. `STOP`/`ABORT`/`HOLD`/`PAUSE` exist but belong to exception handling (item 2316).

---

## 2. Two kinds of procedure - only one ends by itself

**`[CITED]`** - **upgraded from `[DERIVED]` on 2026-08-05, Blatt 4 now read.** This section used to
rest on our own docstring at `mtp/model.py:184-186` because Table 30 was unread. Table 30 turns out to
be nearly empty of semantics (*"IsSelfCompleting BOOL - 1: Procedure is self-completing. 0: Procedure
is not self-completing"*) - but the behaviour is stated outright in three other places:

> **§6.2.3.2 Continuous procedures** - *"For continuous procedures, the `Complete` command to
> terminate the service is sent to the PEA by the POL or the operator depending on the service mode
> according to Section 6.2.1."*
>
> **§6.2.2** (the Figure 3 narrative) - *"The state transitions (commands) that can be requested by the
> POL are: Start, **Complete (only for continuous procedures, see Section 6.2.3.2)**, Reset, …"*
>
> **§6.2.3.1 Self-completing procedures** - *"In a self-completing procedure, the state change 'SC'
> for the planned termination of the service (state change from Execute to Completing) **is triggered
> by the service itself**. The POL or the operator can track the state transition via the states
> Completing and Completed. Termination of the service by PEA-external access is **only possible by
> means of the state transitions Stop and Abort**."*
>
> **Table 36 #4b** - `IsSelfCompleting` is set true *"if the service terminates itself after successful
> execution."*

So `Complete` is a POL command **for continuous procedures only** - and for a self-completing one it
is not merely unnecessary but **not offered**: the only external terminations are `Stop` and `Abort`.
*(This also makes `virtual_pea/state_machine.py:118-119` - which puts `COMPLETE` in `CommandEn` only
when the procedure is not self-completing - standards-conformant rather than a convenience.)*

This is 2658-4 **extending** ISA-88, not contradicting it: ISA-88 assumes a phase runs to completion,
but a modular PEA service may be *continuous*, so 2658-4 adds `Command.COMPLETE` (`state/codes.py:52`)
to terminate one. ISA-88's own command list has no COMPLETE.

**Without this, a continuous step never terminates and the recipe deadlocks.**

**`[DERIVED]` A step therefore has two shapes, chosen by the procedure's own flag:**

| | self-completing | continuous (`is_self_completing = False`) |
|---|---|---|
| who decides the work is done | **the PEA** - it walks to `COMPLETED` | **the recipe** - nothing ends it otherwise |
| the receptivity means | an *additional* gate after completion (usually `=1`) | **the completion criterion itself** |
| order | terminate → receptivity → advance | receptivity → send `COMPLETE` → terminate → advance |

**`[CITED]`** ISA-88 contemplates exactly this, §7.4 EXAMPLE 7: *"The STOP command might also be used
outside of exception handling by an operator to end a phase when its normal activity such as a
titration has run to satisfactory completion but the final target condition specified in the running
equipment phase has not yet been totally reached."*

**`[CITED]`** HC30 ships one of each, so both shapes are testable against the real fixture:
`HC30_Stirring_Duration` (id 2, self-completing) · `HC30_Stirring_Continous` (id 1, not).

```
SELF-COMPLETING                          CONTINUOUS
 1 handshake  [2658-4 §6.2.1]  ← §4a      1 handshake  [2658-4 §6.2.1]  ← §4a
 2 ensure IDLE (§4)                       2 ensure IDLE (§4)
 3 select procedure + params              3 select procedure + params
 4 send START                             4 send START
 5 wait until it leaves IDLE              5 wait until it leaves IDLE
 6 ████ PEA works, reaches COMPLETED      6 ████ PEA holds EXECUTE indefinitely
 7 LATCH the final state (§5)             7 receptivity evaluated  ← decides "done"
 8 receptivity evaluated (gate 2)         8 send COMPLETE → await COMPLETED
                                          9 LATCH the final state (§5)
 9 send RESET → IDLE                     10 send RESET → IDLE
```

> **Two orderings corrected here on 2026-08-05.**
>
> **(a) The latch moved *before* the receptivity in the self-completing column.** It used to be drawn
> after it. That contradicted §5 - *"the engine records which final state was reached **at the instant
> it observes it**"* - and §3, which makes gate #1 read that latched record. Gate 2 cannot be evaluated
> before gate 1 holds, and gate 1 *is* the latch. The continuous column was already correct.
>
> **(b) The handshake moved *before* "ensure IDLE".** `RESET` travels on `CommandExt`, which
> `[2658-4:2022]` §8.2.2.3 says is honoured only in the matching operation mode - so a pre-flight
> `RESET` issued before the mode handshake is **silently dropped**, which is the very failure mode this
> whole document exists to fix. See §4a.

---

## 3. Advancing is two independent gates

**`[CITED]`** §5.3.1 item 1341: *"Steps are initiated only after the immediate predecessor(s) in
series with them **have completed** **and** any intervening **transition conditions are true**."*

| gate | source | who writes it |
|---|---|---|
| predecessor **has completed** | the procedural element reached a Final State | **nobody - structural** |
| transition condition **is true** | the receptivity | the author (**`=1` by default**) |

**`[TITLE-ONLY]`** IEC 60848 §4.5.3 is named *"Clearing of a transition"*; §4.3.2 (read in full) says a
transition *"indicates that an evolution of the activity between two or more steps may evolve. This
evolution is realized by the clearing of the transition."* The load-bearing citation here is ISA-88
item 1341, which we hold in full.

**Both step kinds satisfy item 1341** - what differs is *when the receptivity is evaluated*, never
whether the predecessor completed first:

| | receptivity evaluated | what causes the final state | next step initiated |
|---|---|---|---|
| self-completing | **after** termination | the PEA, on its own | after termination ✓ |
| continuous | **while running** | our `COMPLETE`, sent *because* the receptivity fired | after termination ✓ |

The continuous branch does not advance past a running service - it **ends it, waits, then advances.**

**Consequences**
- The author **never again writes** "service reached COMPLETED" - for a self-completing step that is
  gate #1; for a continuous one it would be circular.
- For a **self-completing** step a transition **cannot** fire mid-step.
- Interrupting a step *without* completing it is exception handling (§7), never a side effect of
  advancing.

---

## 4. Pre-flight: the four cases before `START`

**`[CITED]`** Table B.2, `COMPLETE`: *"Waits in the final state for a RESET command after the
process-oriented task has run to completion."* - a finished service **requires** `RESET` before reuse.

> **Ordering, corrected 2026-08-05 - the handshake comes BEFORE this table, not after it.**
> This table used to say *"`IDLE` → proceed to the handshake"*, implying pre-flight ran first. It
> cannot: row 2 sends `RESET`, `RESET` rides `CommandExt`, and `CommandExt` is honoured only in the
> matching operation mode (§8.2.2.3) - so a `RESET` issued before the handshake is **silently
> dropped**. Run `ensure_automatic_external` first (it is idempotent, `control.py:56`), or go through
> `command_service`, which does it for you. See **§4a**.

| service is | do |
|---|---|
| `IDLE` | proceed - select the procedure, set parameters, `START` |
| a final state - `COMPLETED` / `STOPPED` / `ABORTED` | send `RESET` **via `command_service`**, wait for `IDLE`, then proceed |
| **`RESETTING`** | **already on its way to IDLE - wait for it**, then proceed |
| anything else (`EXECUTE`, `HELD`, `STARTING`, …) | **fail the step loudly** - *"cannot start S2: Stirring on PEA_A is EXECUTE (in use)"* |

**And in every row, `CommandEn` is checked before the command is written** (§4a) - the state above
tells you *which* command to send; `CommandEn` tells you whether the PEA will accept it.

**`[DERIVED]`** rows 3 and 4. `RESETTING` is waited on because it is **post-hoc cleanup with no
owner** - Table B.2: it *"always becomes active between executions … at which time the procedural
element **may no longer be allocated to or viewable from a recipe**"*.

**Why `COMPLETING` / `STOPPING` / `ABORTING` are *not* waited on**, though they also lead to a state we
could `RESET` from: each means **somebody started this service and it is now finishing**. Waiting would
silently queue our step behind another owner and seize the equipment the moment they let go.
**Ownership, not reachability, is the test.** Fail loudly; let the operator decide.

---

## 4a. `CommandEn` - read it before every command, and handshake first

**Added 2026-08-05.** Neither this document nor the build order had it, and it is the clause that
governs the defect the whole correction is about.

### The obligation

**`[CITED]`** `[2658-4:2022]` **§6.2.2.4 Interlocking state transitions**:

> *"The PEA may temporarily lock state transitions **based on existing process values or interlocks at
> the control module level**. … A set bit corresponds to an enabled command. If the bit is not set, the
> state transition is locked. **If a state transition is not currently possible and the command is
> nevertheless requested, the PEA shall not execute this command.** … If the value of CommandEn
> indicates that a command is not requestable, this command **should** not be able to be initiated by
> the operator or the POL. The command **shall** first be enabled by the PEA. Only the PEA has write
> access to the CommandEn variable of its services; the POL and the operator only have read access."*

> **Read the modal verbs exactly.** The POL-side guard is **"should"** - German *"soll"*, a
> recommendation. What is **"shall"** (*"muss"*) is that the PEA must re-enable the command first, and
> that the PEA shall not execute a locked command. So: **not honouring `CommandEn` is not a
> conformance violation - it is a guaranteed silent failure.** We adopt it as binding for Orchestrion
> anyway, because §2's defect *is* this failure.

### Why §4's pre-flight is necessary but **not sufficient**

§4 decides from `StateCur` alone. §6.2.2.4 says the PEA may also lock on **process values and control-
module interlocks** - conditions no state can predict. A service can therefore be `IDLE` with
`StartEnabled` clear. **State is a proxy; `CommandEn` is the truth.**

### The rule

1. **Handshake first.** `CommandExt` is honoured only in the matching operation mode
   (`[2658-4:2022]` §8.2.2.3: *"Depending on the operation mode of the service, the PEA selects the
   corresponding channel."*). `control.send_command` (`control.py:89-91`) writes **without** a
   handshake; `control.command_service` (`control.py:192`) runs `ensure_automatic_external` first and
   is idempotent (`control.py:56` - *"only requests a change when the corresponding `*Act` is not
   already set"*). **Pre-flight must therefore go through `command_service`, never `send_command`.**
2. **Then read `CommandEn`** and refuse to write a command whose bit is clear - naming the command,
   the service and the decoded enabled set, so the operator sees *why*.
3. `state/codes.py:81-89` already provides `decode_command_en(value) -> frozenset[Command]`. The
   subscription already streams it (`connection.py:392`). **Nothing new is needed but the check.**

**`[CITED]` when this was written the POL did none of this.** `grep -n CommandEn
orchestrion/opcua/control.py` returned **one hit - line 189, inside a docstring** that explicitly
delegated the check to the PEA: *"the PEA still only acts if the command's `CommandEn` bit is set
(§6.2.2.4)"*. That delegation is exactly how `START` into `COMPLETED` becomes a silent no-op.
**Since built** - `read_command_en` / `require_command_enabled` now guard every command.

**`[CITED]` corroboration from ISA-88** - the NOTE at items 3452-3455: *"it is generally recommended to
**inhibit the STOP and ABORT commands while in the IDLE, COMPLETE, STOPPED, and RESETTING states**.
This prevents activating the STOPPING, STOPPED, ABORTING, ABORTED, and CLEARING states between
executions of the process-oriented task, during which time the procedural element may no longer be
allocated to or viewable from a recipe."* An informative NOTE, but it independently confirms that a
restricted command set between executions is intended, not an implementation shortcut.

---

## 5. `RESET` - mandatory, and latched before it is sent

**`[CITED]`** Table B.2, `RESETTING`: *"Prepares the procedural element and equipment for the next
execution … Upon completion, control passes to IDLE.* **Note: This state always becomes active between
executions of the Process-oriented task**, *at which time the procedural element may no longer be
allocated to or viewable from a recipe."*

So `RESET` is **not optional housekeeping** - RESETTING *always* occurs between executions.

**`[DERIVED]` Latch before reset.** Gate #1 advances on "reached a Final State", but `RESET` drives
`COMPLETED → RESETTING → IDLE` - **tidying up erases the evidence.** The engine records *which* final
state was reached at the instant it observes it; gate #1 reads that **latched record, never live
state**.

This permanently closes the stale-state bug class: completion is observed **once**, at a known instant,
never re-derived from a cache that has since moved on.

**`[OURS]` When `RESET` is sent: on advance, not on termination.** Decided 2026-08-06 - see §12 item
**0a** for the reasoning. The step therefore sits in its final state for as long as it is *terminated
but not yet advanced* (§8), which is what makes *"S1 finished, waiting for Temp > 80"* observable on
the PEA and not just in our own run state. The latch above is what makes this safe to do late: the
final state is already recorded, so nothing depends on the PEA still holding it.

---

## 6. The complete 16-state classification

**`[CITED]`** items 2382-2388 define exactly two kinds of procedural state:

> *"A state (name ending in "ING") in which the procedural element may orchestrate a defined set of
> actions… **Transition from an acting state occurs either upon completion of its defined task or upon
> receipt of a suitable command**."*
>
> *"A state for which the procedural element has previously achieved a defined set of conditions and is
> not permitted to direct any immediate actions… **Transition from a waiting state occurs only upon
> receipt of a suitable command**."*

| kind | states | n | engine behaviour |
|---|---|---|---|
| **acting** | `STARTING` `EXECUTE` `COMPLETING` `RESETTING` `HOLDING` `UNHOLDING` `PAUSING` `RESUMING` `STOPPING` `ABORTING` | 10 | the PEA is working - keep waiting |
| **waiting** - initial | `IDLE` | 1 | ready to be started |
| **waiting** - recoverable interrupt | `HELD` `PAUSED` | 2 | needs an **operator** command → run reports held/paused and waits (§7) |
| **waiting** - terminal normal | `COMPLETED` | 1 | step terminated OK → latch, `RESET` |
| **waiting** - terminal abnormal | `STOPPED` `ABORTED` | 2 | run fails (§7) |

16 total. The mapping must be **exhaustive - no default arm**, so a future Table 14 addition is a type
error rather than silently "keep waiting". `decode_state` already raises `UnknownServiceState` outside
Table 14 - keep it.

**`[DERIVED]`** placing `EXECUTE` under *acting*: item 2382's test is literally "name ending in ING",
and 2658-4 renamed RUNNING to `EXECUTE`. Table B.2's RUNNING description (*"Directs normal sequencing
of the process-oriented task… Upon completion, control passes to COMPLETING"*) makes it unambiguous,
but the name no longer matches the stated test.

Note the asymmetry: for a **continuous** procedure `EXECUTE` is a *steady* state the service never
leaves unaided - which is exactly why §2 must send `COMPLETE` rather than wait.

---

## 7. Exception handling - all four §7.4 levels

**`[CITED]`** items 2341-2369 grade exception response by severity; the dividing line is whether the
task can return to normal running:

| | command | ISA-88 | recoverable |
|---|---|---|---|
| 1 | `PAUSE` | *"a short-term stop … that **does not require any additional shutdown or restarting actions**"* | **yes** → `RESUME` |
| 2 | `HOLD` | *"operator intervention for correction of minor process deviations **from which the normal running state can be manually resumed**"* | **yes** → `UNHOLD`/`RESTART` |
| 3 | `STOP` | *"a controlled normal stop, from which the current execution … **cannot be returned to its normal running state**"* | no |
| 4 | `ABORT` | *"an immediate abnormal stop … requiring manual reworking, reclassification, or removal of the material"* | no |

**`[OURS]` levels 1-2 → the run reports held/paused and waits indefinitely**, naming the step and
state; when the service returns to `EXECUTE` the run resumes on its own. No clock, nothing fails.
Consistent with §6 - a waiting state needs a command, here the operator's.

> When this was written the path did not exist. §7.4 EXAMPLE 5 - *"A batch may go into HOLD in response
> to a limit switch indicating a valve failure"* - ended with `engine.py:100-103` declaring **`failed` /
> "timed out"** after 60 s. **The operator did exactly what `HOLD` is for and we killed their batch for
> the wrong reason.** **Since built**: held/paused are reported, the run waits, and the
> global timeout is gone (§11).

**`[OURS]` levels 3-4 → the run fails**: `status = "failed"`, `error` naming the step and final state;
no further steps start. **`[CITED]`** item 3450 says the parent *"**may** progress"* - deliberately
open, so this is our choice, grounded in items 2355/2365 (non-recoverable).

**`[OURS]` sibling steps on failure - left running, and reported.** Run-level propagation is a later
increment, so the run's error must **name every step still executing**. A **known limitation** - a
failed batch can leave equipment running and the operator must be told, not left to discover it.

**`[CITED]`** `state/codes.py:36` - 2658-4 gives us `RESET, START, STOP, HOLD, UNHOLD, PAUSE, RESUME,
ABORT, RESTART, COMPLETE`, 1:1 with §7.5. Nothing is blocked by the interface; it is simply unused.

---

## 8. A step has four states, not two

**`[DERIVED]`** `RecipeRun` had only `active`/`done`. This model needs the four below - **built as
the `StepState` enum** (`RUNNING · COMPLETING · TERMINATED · DONE`):

| | meaning | live chart |
|---|---|---|
| **running** | service in an acting state | step animated |
| **completing** | *continuous only* - receptivity fired, `COMPLETE` sent, awaiting `COMPLETED` | *"S1 finishing…"* |
| **terminated** | final state latched (self-completing: awaiting the receptivity) | step done, transition pending |
| **done** | the transition fired | step settled |

For a self-completing step with `=1`, *terminated* is momentary; with `Temp > 80` it sits there
indefinitely - and *"S1 finished, waiting for Temp > 80"* is precisely what an operator must see.

---

## 9. `Elapsed` counts from when the transition became *enabled*

**`[OURS]`** - one rule from which both step kinds fall out correctly. `engine.py:110` measured from
when the from-steps **started**, which under two gates is ambiguous. **Since changed**;
the engine now times from the transition-enabled instant.

**Rule: `Elapsed` measures from the instant the transition became *enabled*** ("enabled" as defined by
§3's table, not by an unread clause):

| step kind | when the transition is enabled | so `Elapsed 30` means |
|---|---|---|
| **continuous** | immediately - the step is running and the receptivity *is* the completion criterion | **"run for 30 s, then complete it"** - a duration |
| **self-completing** | only once the step has terminated (gate #1) | **"wait 30 s after it finishes"** - a dwell |

For an AND convergence with several `from_ids`, count from the **last** one to become eligible -
mirroring the existing `max(...)` at `engine.py:110`.

`conditions.is_met` is **unchanged**; only the engine's computation of `elapsed` moves, from
`_active_since` to a transition-enabled timestamp.

---

## 10. Run status - observe now, command later

**`[CITED]`** items 2326-2331: exception handling is managed *through state commands on procedural
elements*, and a recipe procedure **is** a procedural element.

- **Now:** run status is **observed**, derived from its steps - `running | held | paused | completed |
  failed | aborted`. This is what fixes §7.
- **Later:** run-level `PAUSE`/`HOLD`/`STOP`/`ABORT` propagating down to active steps.

**`[OURS]`** the split and any propagation rule. **`[CITED]`** items 2233-2235 / 2282-2285: *"The
propagation can be in either direction … IEC 61512 **does not specify propagation rules**."* Annex C.3
(items 3630-3640) confirms §7.4 is short by intent. **The four levels are binding; propagation is ours.**

---

## 11. No global timeout; fail on disconnect

**`[OURS]`** `engine.py:71` `timeout: float = 60.0` capped the **whole run**. Real batches run for
hours; ISA-88 has no such concept; and it is what turns a held batch into a false `failed`. The default
became `None` - a run ends when the chart ends it, or on abort. Tests pass a short timeout explicitly.
**Since built**, together with the `try`/`except` around `drive_step` that the timeout had
been accidentally masking.

**`[DERIVED]`** but it was the only backstop against a **dead PEA**: `registry.snapshot(pea_id)` returns
`None` when disconnected → `state_of` returns `None` → every condition false → **the run waits forever
with no indication why**.

**`[OURS]` a PEA disconnecting while it holds an active step fails the run.** Not "held": `HELD` means
an operator is deliberately intervening and the state is *known*. A disconnect means we have **lost
observability of a running procedural element** - it may have completed, aborted or reset while we were
blind, and we cannot honestly claim to know.

**`[DERIVED]` this needs an interface change.** `StateOf = Callable[[int, str], str | None]`
(`conditions.py:19`) returns `None` for **both** "disconnected" and "no such service", and the engine is
deliberately decoupled from the registry (`engine.py:23-26` - callbacks, so tests pass fakes), so it has
**no registry handle**. Therefore `RecipeEngine` gains one injected callback:

```python
is_connected: Callable[[int], bool]   # production: registry.snapshot(pea_id) is not None
```

This preserves the decoupling rather than reaching around it.

---

## 12. Open items

> **Items 0a–0c were opened 2026-08-05 and DECIDED 2026-08-06. Unit 3 is unblocked.**

**0a. DECIDED - `RESET` is sent when the transition fires, not at termination.**

**`[OURS]` on the timing.** ISA-88 mandates *that* it happens - `COMPLETE` *"waits in the final state
for a RESET command"*, RESETTING *"always becomes active between executions"* - but the whole document
was searched and it **never says who issues `RESET` or when.**

Take a self-completing step whose receptivity is `Temp > 80`, ten minutes away:

| choice | the operator sees |
|---|---|
| RESET at termination | the service returns to `IDLE` at once - **indistinguishable from a step that never ran** |
| **RESET when the transition fires** | the service sits in `COMPLETED` - *"S1 finished, waiting for Temp > 80"* |

Two reasons:

1. **§8 already defines a *terminated* step state** whose entire purpose is to show *"finished, waiting
   for the receptivity"*. `COMPLETED` on the PEA says exactly that; `IDLE` throws it away.
2. **`[DERIVED]` Table B.2 puts the ownership boundary at RESETTING**, not at termination: RESETTING
   *"always becomes active between executions of the Process-oriented task, **at which time the
   procedural element may no longer be allocated to or viewable from a recipe**."* Resetting early
   would push the service out of the recipe's ownership **while the recipe still has a pending decision
   about it**. Resetting on advance is what *"between executions"* actually means.

*(The counter-argument - a finished step holds equipment - is real, but it is the **equipment
allocation** gap at item 3 below, and it applies to both choices.)*

**0b + 0c. DECIDED - see [`POL_Recipe_Chart_GRAFCET.md`](POL_Recipe_Chart_GRAFCET.md) §5.**

- **OR-divergence out of a continuous step** - the first receptivity to fire, in priority order,
  **is latched**: `COMPLETE` is sent once, and the recorded branch is taken regardless of what else
  goes true meanwhile. Re-evaluating can **deadlock** (the winning condition falls false during
  `COMPLETING` and no branch is true).
- **AND-convergence over mixed kinds** - the join's receptivity **ends every continuous from-step**:
  condition true **and** all self-completing from-steps terminated → `COMPLETE` to each continuous one
  → await all final → initiate. **Satisfies item 1341 exactly** at the instant of initiation.

Both are `[DERIVED]`, not `[CITED]`. *(Updated 2026-08-08: this used to say "IEC 60848 §6.2.3 is
outside the preview". **The full standard is now held** - `../standards/IEC 60848_2013/` - and §6.2.3
has been read. It does **not** settle these two: it says only that exclusive activation "is not
guaranteed from the structure" and puts the duty on the designer. So the tag stands, but for the
right reason - the clause was read and is silent, rather than unavailable.)* Chart §5 carries the
full reasoning and what was rejected.

---

Not required to build this model, but each is a real gap in it.

1. **`Not` in the condition union** - IEC 60848 §4.3.3 makes the receptivity *"a logical expression
   which is true or false"*. `And`/`Or` **without `Not` is an incomplete boolean algebra**: "advance
   while the service is *not* HELD" is unwritable today. Additive when added.
2. **Formula ↔ step params** - `MasterRecipe.formula` (ISA-88 §6.3.3) is **dead data**; nothing reads
   it, and `RecipeStep.params` are literal numbers. So a recipe **cannot be scaled per batch**, which
   is the formula's entire purpose in ISA-88.
3. **Equipment allocation** - ISA-88 §8.6.3 *"Track and allocate process cell resources"*. §4's
   pre-flight handles the **symptom** (a service is busy → fail loudly) but there is **no ownership
   model**: nothing says "this run holds PEA_A for its duration", so two recipes racing for one PEA is
   resolved by whoever calls `START` first. **[later increment]**
4. **Master vs control recipe** - `model.py:14-15` defers the *control recipe* (the master bound to
   actually-connected PEAs). Everything in §4 is really control-recipe territory: pre-flight only means
   anything against a live, bound PEA. The distinction needs modelling before allocation can be.
   **[later increment]**
5. **Run-level commands** - §10 defers `PAUSE`/`HOLD`/`STOP`/`ABORT` on the *run* (and therefore §7's
   sibling-steps limitation: a failed batch can leave equipment running). Propagation is explicitly
   **not** specified by ISA-88 (items 2233-2235), so it is ours to design.

## 13. What this contradicted in the code - ALL FIXED

> **Historical, as of 2026-08-08.** Every row below was a real contradiction when this document was
> written; **all of them were fixed by **,
> units 1–8. Kept as the record of what was wrong and why, **not as a to-do list** - do not read it
> as outstanding work. What genuinely remains is [`OUTSTANDING.md`](OUTSTANDING.md).

| file | was | became |
|---|---|---|
| `engine.py:113-115` | `done` = "a transition fired" | `done` = the phase **terminated** (§1, §5) |
| `engine.py` | never sends `RESET` | mandatory both ends (§5) |
| `engine.py` | never sends `COMPLETE` | required for continuous steps (§2) |
| `engine.py:71` | `timeout = 60.0` global | `None` (§11) |
| `engine.py:106` | iterates transitions, mutates `run.active` mid-loop | deliberate, grouped, at most one fire |
| `engine.py:110` | elapsed from step **start** | from transition **enabled** (§9) |
| `control.py:171-180` | `start_service` returns after writing Start | pre-flight (§4) + await-started (§1) |
| - | no `HELD`/`PAUSED` concept | §7 levels 1-2 |

**Added 2026-08-05 - each verified by reading the file, not inferred. All four also fixed:**

| file | was | became |
|---|---|---|
| `control.py` | **`CommandEn` is never read.** `grep -n CommandEn` → line 189 only, a docstring | guard every command (**§4a**) |
| `engine.py:92-96` | activates **every** step that no transition targets - so a chart with two initial steps starts **both** on live equipment | exactly one initial step, enforced **server-side** as well as in the builder (chart §2) |
| `engine.py` | **no `try`/`except` anywhere.** A `drive_step` exception escapes `run()`, so `status="failed"` is reachable *only* via the timeout §11 deletes | a failed drive fails the run, naming the step |
| `engine.py:84-86` | `abort()` sets a flag and commands **no PEA** - an aborted run leaves every service running | at minimum, report every still-running service (as §7 does for failure); commanding them is §10's later increment |
