import { describe, expect, it } from 'vitest'
import type { RunReport, RunStatus, StepState } from '../api/types'
import {
  elapsedSeconds,
  isFailure,
  isLive,
  stepViews,
  summarizeRun,
  transitionPhase,
} from './runView'

function report(over: Partial<RunReport> = {}): RunReport {
  return {
    run_id: 1,
    project_id: 1,
    recipe_id: 1,
    recipe_name: 'Batch-42',
    status: 'running',
    error: null,
    steps: {},
    terminal: {},
    started_at: '2026-09-06T10:00:00+00:00',
    finished_at: null,
    events: [],
    ...over,
  }
}

const views = (steps: Record<string, StepState>, terminal: Record<string, string> = {}) =>
  stepViews(Object.keys(steps), report({ steps, terminal }))

describe('stepViews', () => {
  it('calls a step the run has not reached `pending`, not missing', () => {
    // The engine only tracks steps it has activated, so absence is meaningful.
    const v = stepViews(['s1', 's2'], report({ steps: { s1: 'running' } }))
    expect(v.get('s1')!.phase).toBe('running')
    expect(v.get('s2')!.phase).toBe('pending')
  })

  it('passes the engine\'s four states through unrenamed', () => {
    // Rule 1 edge: the vocabulary is the engine's (step model §8). This test exists to fail
    // if someone "tidies" the names into UI words.
    const v = views({ a: 'running', b: 'completing', c: 'terminated', d: 'done' })
    expect([...v.values()].map((x) => x.phase)).toEqual([
      'running', 'completing', 'terminated', 'done',
    ])
  })

  it('carries the latched terminal state', () => {
    const v = views({ s1: 'done' }, { s1: 'COMPLETED' })
    expect(v.get('s1')!.terminal).toBe('COMPLETED')
    expect(v.get('s1')!.abnormal).toBe(false)
  })

  it('marks STOPPED and ABORTED as abnormal, COMPLETED as not', () => {
    // [IEC 61512-1] items 2355-2369: STOP/ABORT are the non-recoverable levels, and the run
    // fails on them — so they must not be drawn as a normal finish.
    expect(views({ s: 'terminated' }, { s: 'STOPPED' }).get('s')!.abnormal).toBe(true)
    expect(views({ s: 'terminated' }, { s: 'ABORTED' }).get('s')!.abnormal).toBe(true)
    expect(views({ s: 'terminated' }, { s: 'COMPLETED' }).get('s')!.abnormal).toBe(false)
  })

  it('is all-pending when there is no run at all', () => {
    const v = stepViews(['s1', 's2'], null)
    expect([...v.values()].every((x) => x.phase === 'pending' && !x.abnormal)).toBe(true)
  })
})

describe('transitionPhase', () => {
  it('is `waiting` when every preceding step has terminated', () => {
    // The state the four-state step model exists to make visible: "S1 finished, waiting for
    // Temp > 80". Gate 1 is satisfied; the receptivity is not.
    const v = views({ s1: 'terminated' })
    expect(transitionPhase(['s1'], v)).toBe('waiting')
  })

  it('is `fired` only once every preceding step is done', () => {
    expect(transitionPhase(['s1', 's2'], views({ s1: 'done', s2: 'done' }))).toBe('fired')
    expect(transitionPhase(['s1', 's2'], views({ s1: 'done', s2: 'terminated' }))).toBe('idle')
  })

  it('a join is not `waiting` until ALL of its branches have terminated', () => {
    const v = views({ s1: 'terminated', s2: 'running' })
    expect(transitionPhase(['s1', 's2'], v)).toBe('idle')
  })

  it('is `idle` for a step still running — including a continuous one', () => {
    // Deliberate: a transition out of a *continuous* step can fire while that step still
    // reads `running`, because its receptivity IS the completion criterion. This module
    // describes the report and does not predict the engine, so it says `idle` here. Pinned
    // so the limitation is a decision on record, not something to "fix" into a wrong guess.
    expect(transitionPhase(['s1'], views({ s1: 'running' }))).toBe('idle')
    expect(transitionPhase(['s1'], views({ s1: 'completing' }))).toBe('idle')
  })

  it('is `idle` for an unreached step and for no from-steps at all', () => {
    expect(transitionPhase(['nope'], views({}))).toBe('idle')
    expect(transitionPhase([], views({}))).toBe('idle')
  })
})

describe('isLive / isFailure', () => {
  it('treats held and paused as live, because the run resumes by itself', () => {
    // Step model §7 levels 1-2: both are recoverable, the run waits with no clock and picks
    // up again when the operator releases the service. A view that stopped polling here
    // would go blind exactly when someone is intervening.
    expect((['running', 'held', 'paused'] as RunStatus[]).every(isLive)).toBe(true)
    expect((['completed', 'failed', 'aborted'] as RunStatus[]).some(isLive)).toBe(false)
  })

  it('counts failed and aborted as failure, completed as not', () => {
    expect(isFailure('failed')).toBe(true)
    expect(isFailure('aborted')).toBe(true)
    expect(isFailure('completed')).toBe(false)
  })
})

describe('summarizeRun', () => {
  it('counts settled steps while running', () => {
    const r = report({ steps: { s1: 'done', s2: 'running' } })
    expect(summarizeRun(r)).toBe('running · 1/2 steps settled')
  })

  it('gives the reason when the run failed', () => {
    const r = report({ status: 'failed', error: 'lost connection to PEA 2' })
    expect(summarizeRun(r)).toContain('lost connection to PEA 2')
  })

  it('never leaves a failure unexplained', () => {
    expect(summarizeRun(report({ status: 'failed', error: null }))).toContain('no reason given')
  })

  it('says who the run is waiting for when held or paused', () => {
    expect(summarizeRun(report({ status: 'held' }))).toContain('operator')
    expect(summarizeRun(report({ status: 'paused' }))).toContain('operator')
  })
})

describe('elapsedSeconds', () => {
  it('counts from the start while running', () => {
    const now = Date.parse('2026-09-06T10:00:42+00:00')
    expect(elapsedSeconds(report(), now)).toBe(42)
  })

  it('stops at finished_at, so a finished run does not keep counting', () => {
    const r = report({ status: 'completed', finished_at: '2026-09-06T10:00:30+00:00' })
    const muchLater = Date.parse('2026-09-06T11:00:00+00:00')
    expect(elapsedSeconds(r, muchLater)).toBe(30)
  })

  it('never goes negative on a clock skew', () => {
    const before = Date.parse('2026-09-06T09:59:00+00:00')
    expect(elapsedSeconds(report(), before)).toBe(0)
  })
})
