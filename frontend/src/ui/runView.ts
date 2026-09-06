// Turning a run report into what the chart should show — pure, framework-free, tested.
//
// Authority: `docs/POL_Step_Model_ISA88.md` §8 (a step has four states, not two) and §5
// (the latch). The wire shape is `recipe/runs.py::RunRecord.to_dict()`.
//
// ── THE ONE RULE 1 EDGE IN AN OTHERWISE FREE-DESIGN MILESTONE ────────────────────────────
// How a running step is *drawn* is ours — [IEC 60848:2013] Table 2 [7] NOTE 4 puts transition
// symbolism outside the standard entirely. **The vocabulary is not ours.** The four step
// states are the engine's `StepState` (step model §8); the latched values in `terminal` are
// [2658-4:2022] Table 14 `ServiceState` names; acting-versus-waiting is ISA-88 (items
// 2382-2390, `state/classification.py`). So this module **renames nothing**. It maps each
// state to a label and a tone, and where it needs a word for "not yet reached" it adds
// exactly one — `pending` — which describes the *absence* of a step from the report rather
// than a state the engine has.
//
// ── WHY THE TRANSITION VIEW IS DELIBERATELY NOT THE ENGINE'S GATE ────────────────────────
// It would be easy to reimplement `_eligible` here and light up "this transition can fire".
// That is the trap this codebase has already been bitten by twice: a builder rule mirroring
// a server rule drifts, and the lax side wins (the nested-`Always` gap). Worse, `_eligible`
// depends on whether a from-step's procedure is *continuous* — for one of those, gate 1 is
// satisfied while it is still RUNNING, because its receptivity IS its completion criterion.
// Getting that subtly wrong would draw a confident, false picture of why a run is stuck.
//
// So this describes **only what the report shows**: every from-step has terminated and the
// transition has not fired yet, therefore the run is waiting here. That statement is true
// regardless of procedure kind, needs nothing the report does not carry, and cannot drift —
// because it is not a copy of a decision, it is a reading of a result.

import type { RunReport, RunStatus, StepState } from '../api/types'

/** What a step looks like on the chart during a run.
 *
 *  Four of the five are the engine's own `StepState`, unchanged. `pending` is the fifth and
 *  means **the report does not mention this step**: the run has not reached it. */
export type StepPhase = 'pending' | StepState

export interface StepRunView {
  phase: StepPhase
  /** The latched Final State, once there is one — a Table 14 name (`COMPLETED`, `STOPPED`,
   *  `ABORTED`). Read from `run.terminal`, which the engine records **at the instant of
   *  observation**, because `RESET` afterwards drives COMPLETED → RESETTING → IDLE and
   *  erases the evidence (step model §5). */
  terminal?: string
  /** The step terminated **abnormally** — STOP/ABORT, the two non-recoverable exception
   *  levels ([IEC 61512-1] items 2355-2369). The run fails on these, so they are drawn as
   *  failure rather than as completion. */
  abnormal: boolean
  /** `HELD` or `PAUSED` — an operator is intervening on **this** step, right now.
   *
   *  Read from the report rather than inferred. The tempting inference — "the run is held,
   *  so shade the running steps" — is wrong the moment two branches run in parallel: it
   *  would label a genuinely working step as held. The engine knows exactly which service
   *  it saw interrupted, so it says so, and this reads it. */
  interrupted?: string
}

/** Terminal states, by how ISA-88 grades them — `state/classification.py`'s
 *  TERMINAL_NORMAL versus TERMINAL_ABNORMAL, which is the distinction that decides whether
 *  a run continues or fails. */
const ABNORMAL_TERMINALS = new Set(['STOPPED', 'ABORTED'])

/** Every step's display state. Steps absent from the report are `pending`, not missing. */
export function stepViews(
  stepIds: readonly string[],
  report: RunReport | null,
): Map<string, StepRunView> {
  const views = new Map<string, StepRunView>()
  for (const id of stepIds) {
    const phase: StepPhase = report?.steps[id] ?? 'pending'
    const terminal = report?.terminal[id]
    views.set(id, {
      phase,
      terminal,
      abnormal: terminal !== undefined && ABNORMAL_TERMINALS.has(terminal),
      // `?? undefined` because an older report (or a fake in a test) may not carry the map
      // at all; an absent field must read as "not interrupted", never as a crash.
      interrupted: report?.interrupted?.[id] ?? undefined,
    })
  }
  return views
}

/** What the chart shows on a transition during a run.
 *
 *  `waiting` is the one worth having: every preceding step has **terminated** and the
 *  transition still has not fired, so the run is sitting on this receptivity. That is
 *  precisely *"S1 finished, waiting for Temp > 80"* — the observable state the four-state
 *  step model exists to make visible (step model §8, §12 item 0a).
 *
 *  ⚠ Not a claim about eligibility — see the header. A transition out of a *continuous*
 *  step is perfectly able to fire while that step still reads `running`, and this will call
 *  that `idle`. It is describing the report, not predicting the engine. */
export type TransitionPhase = 'idle' | 'waiting' | 'fired'

export function transitionPhase(
  fromStepIds: readonly string[],
  views: ReadonlyMap<string, StepRunView>,
): TransitionPhase {
  if (fromStepIds.length === 0) return 'idle'
  const phases = fromStepIds.map((id) => views.get(id)?.phase ?? 'pending')
  if (phases.every((p) => p === 'done')) return 'fired'
  if (phases.every((p) => p === 'terminated')) return 'waiting'
  return 'idle'
}

/** Is this run still going? `held` and `paused` are **live** — the operator is intervening
 *  and the run resumes on its own when they are done (step model §7 levels 1-2), so the view
 *  must keep polling rather than treating them as an ending. */
export function isLive(status: RunStatus): boolean {
  return status === 'running' || status === 'held' || status === 'paused'
}

/** Did the run end badly? Drives the tone of the summary, nothing else. */
export function isFailure(status: RunStatus): boolean {
  return status === 'failed' || status === 'aborted'
}

/** A one-line human summary of where a run is. */
export function summarizeRun(report: RunReport): string {
  const total = Object.keys(report.steps).length
  const done = Object.values(report.steps).filter((s) => s === 'done').length
  switch (report.status) {
    case 'completed':
      return `completed · ${done} step${done === 1 ? '' : 's'}`
    case 'failed':
      return `failed · ${report.error ?? 'no reason given'}`
    case 'aborted':
      return `aborted${report.error ? ` · ${report.error}` : ''}`
    case 'held':
      return 'held · waiting for the operator to release the service'
    case 'paused':
      return 'paused · waiting for the operator to resume the service'
    default:
      return `running · ${done}/${total} step${total === 1 ? '' : 's'} settled`
  }
}

/** How long the run has been going, in whole seconds.
 *
 *  From `finished_at` once it exists, so a finished run stops counting; `now` is injected
 *  rather than read here, which is what keeps this module pure and the test deterministic. */
export function elapsedSeconds(report: RunReport, now: number): number {
  const started = Date.parse(report.started_at)
  if (Number.isNaN(started)) return 0
  const end = report.finished_at ? Date.parse(report.finished_at) : now
  return Math.max(0, Math.round((end - started) / 1000))
}
