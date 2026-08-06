import { describe, expect, it } from 'vitest'
import type { Condition, MasterRecipe, Transition } from '../api/types'
import { graphToTransitions, recipeToGraph, START_ID, END_ID, type GraphEdge, type GraphNode } from './recipeGraph'

const step = (id: string, pea = 1, service = 'Stirring', proc = 1): GraphNode => ({
  id, kind: 'step', pea_id: pea, service, procedure_id: proc, params: {},
})
const cond = (state: string, pea = 1, service = 'Stirring'): Condition => ({ type: 'StateReached', pea_id: pea, service, state })
const trans = (id: string, condition?: Condition): GraphNode => ({ id, kind: 'transition', condition })
const andBar = (id: string): GraphNode => ({ id, kind: 'and' })
const orBar = (id: string): GraphNode => ({ id, kind: 'or' })
const e = (source: string, target: string): GraphEdge => ({ source, target })

function canonCond(c: Condition): Condition {
  if (c.type === 'And' || c.type === 'Or') {
    const conditions = c.conditions.map(canonCond).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
    return { ...c, conditions }
  }
  return c
}
function canon(ts: Transition[]) {
  return ts
    .map((t) => ({ from: [...t.from_ids].sort(), to: [...t.to_ids].sort(), condition: canonCond(t.condition) }))
    .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
}
function recipeOf(nodes: GraphNode[], transitions: Transition[]): MasterRecipe {
  return {
    header: { name: 'x', version: 1, author: '', product: '' },
    formula: {},
    steps: nodes.filter((n) => n.kind === 'step').map((n) => ({
      id: n.id, pea_id: n.pea_id!, service: n.service!, procedure_id: n.procedure_id!, params: n.params ?? {},
    })),
    transitions,
  }
}
const roundTrip = (nodes: GraphNode[], edges: GraphEdge[]) => {
  const t1 = graphToTransitions(nodes, edges).transitions
  const g2 = recipeToGraph(recipeOf(nodes, t1))
  return { t1, t2: graphToTransitions(g2.nodes, g2.edges).transitions, g2 }
}

describe('GRAFCET series', () => {
  it('start → s1 → T → s2 → T → END', () => {
    const nodes = [{ id: START_ID, kind: 'start' } as GraphNode, step('s1'), step('s2'), { id: END_ID, kind: 'end' } as GraphNode, trans('t1', cond('COMPLETED')), trans('t2', cond('COMPLETED', 2))]
    const edges = [e(START_ID, 's1'), e('s1', 't1'), e('t1', 's2'), e('s2', 't2'), e('t2', END_ID)]
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    expect(canon(transitions)).toEqual(canon([
      { from_ids: ['s1'], to_ids: ['s2'], condition: cond('COMPLETED') },
      { from_ids: ['s2'], to_ids: [END_ID], condition: cond('COMPLETED', 2) },
    ]))
  })

  it('defaults a bare transition to source ✓ COMPLETED', () => {
    const nodes = [step('s1'), step('s2'), trans('t1')]
    const { transitions } = graphToTransitions(nodes, [e('s1', 't1'), e('t1', 's2')])
    expect(transitions[0].condition).toEqual(cond('COMPLETED'))
  })
})

describe('AND bar (═) — simultaneous', () => {
  it('divergence: s1 → T → ═ → {s2,s3}', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), trans('t1', cond('COMPLETED')), andBar('a1')]
    const edges = [e('s1', 't1'), e('t1', 'a1'), e('a1', 's2'), e('a1', 's3')]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect(transitions[0].from_ids).toEqual(['s1'])
    expect([...transitions[0].to_ids].sort()).toEqual(['s2', 's3'])
  })

  it('convergence: {s1,s2} → ═ → T → s3', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), trans('t1', cond('EXECUTE')), andBar('a1')]
    const edges = [e('s1', 'a1'), e('s2', 'a1'), e('a1', 't1'), e('t1', 's3')]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect([...transitions[0].from_ids].sort()).toEqual(['s1', 's2'])
    expect(transitions[0].to_ids).toEqual(['s3'])
    expect(transitions[0].condition).toEqual(cond('EXECUTE'))
  })

  it('round-trips an AND split→join diamond', () => {
    const nodes = [
      step('s0'), step('s1'), step('s2'), step('s3'),
      trans('t1', cond('COMPLETED')), trans('t2', cond('EXECUTE')), trans('t3', cond('COMPLETED', 3)),
      andBar('a1'), andBar('a2'), { id: START_ID, kind: 'start' } as GraphNode, { id: END_ID, kind: 'end' } as GraphNode,
    ]
    const edges = [
      e(START_ID, 's0'), e('s0', 't1'), e('t1', 'a1'), e('a1', 's1'), e('a1', 's2'),
      e('s1', 'a2'), e('s2', 'a2'), e('a2', 't2'), e('t2', 's3'), e('s3', 't3'), e('t3', END_ID),
    ]
    const { t1, t2 } = roundTrip(nodes, edges)
    expect(canon(t2)).toEqual(canon(t1))
  })
})

describe('OR bar (─) — selection', () => {
  it('divergence: s1 → ─ → {T→s2, T→s3}', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), orBar('o1'), trans('t1', cond('EXECUTE')), trans('t2', cond('HELD'))]
    const edges = [e('s1', 'o1'), e('o1', 't1'), e('t1', 's2'), e('o1', 't2'), e('t2', 's3')]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.from_ids[0] === 's1' && t.to_ids.length === 1)).toBe(true)
  })

  it('convergence: {s1→T, s2→T} → ─ → s3', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), orBar('o1'), trans('t1', cond('COMPLETED')), trans('t2', cond('COMPLETED', 2))]
    const edges = [e('s1', 't1'), e('t1', 'o1'), e('s2', 't2'), e('t2', 'o1'), e('o1', 's3')]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.to_ids[0] === 's3' && t.from_ids.length === 1)).toBe(true)
  })

  it('round-trips an OR divergence (and rebuilds the bar)', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), orBar('o1'), trans('t1', cond('EXECUTE')), trans('t2', cond('HELD'))]
    const edges = [e('s1', 'o1'), e('o1', 't1'), e('t1', 's2'), e('o1', 't2'), e('t2', 's3')]
    const { t1, t2, g2 } = roundTrip(nodes, edges)
    expect(g2.nodes.some((n) => n.kind === 'or')).toBe(true)
    expect(canon(t2)).toEqual(canon(t1))
  })

  it('round-trips an OR convergence (and rebuilds the bar)', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), orBar('o1'), trans('t1', cond('COMPLETED')), trans('t2', cond('COMPLETED', 2))]
    const edges = [e('s1', 't1'), e('t1', 'o1'), e('s2', 't2'), e('t2', 'o1'), e('o1', 's3')]
    const { t1, t2, g2 } = roundTrip(nodes, edges)
    expect(g2.nodes.some((n) => n.kind === 'or')).toBe(true)
    expect(canon(t2)).toEqual(canon(t1))
  })
})

describe('GRAFCET alternation rules', () => {
  it('rejects a step wired straight to another step', () => {
    expect(graphToTransitions([step('s1'), step('s2')], [e('s1', 's2')]).error).toMatch(/alternates steps and transitions/i)
  })

  it('rejects two transitions wired together', () => {
    const nodes = [step('s1'), step('s2'), trans('t1'), trans('t2')]
    expect(graphToTransitions(nodes, [e('s1', 't1'), e('t1', 't2'), e('t2', 's2')]).error).toMatch(/alternates steps and transitions/i)
  })

  it('rejects a dangling transition (no step before or after)', () => {
    expect(graphToTransitions([step('s1'), trans('t1')], [e('s1', 't1')]).error).toMatch(/before it and one after/i)
  })

  it('rejects an OR bar with a step on both sides (no transition between the steps)', () => {
    const nodes = [step('s1'), step('s2'), orBar('o1')]
    expect(graphToTransitions(nodes, [e('s1', 'o1'), e('o1', 's2')]).error).toMatch(/OR bar is wired wrong/i)
  })

  it('rejects an AND bar with a step on both sides', () => {
    const nodes = [step('s1'), step('s2'), andBar('a1')]
    expect(graphToTransitions(nodes, [e('s1', 'a1'), e('a1', 's2')]).error).toMatch(/AND bar is wired wrong/i)
  })

  it('rejects a one-branch OR (a single transition into the OR)', () => {
    const nodes = [step('s1'), step('s2'), orBar('o1'), trans('t1', cond('COMPLETED'))]
    // s1 → t1 → o1 → s2  : only ONE branch transition, not a real selection
    expect(graphToTransitions(nodes, [e('s1', 't1'), e('t1', 'o1'), e('o1', 's2')]).error).toMatch(/OR bar is wired wrong/i)
  })

  it('rejects a one-branch AND (a single step out of the AND)', () => {
    const nodes = [step('s1'), step('s2'), andBar('a1'), trans('t1', cond('COMPLETED'))]
    // s1 → t1 → a1 → s2  : only ONE parallel step, not a real split
    expect(graphToTransitions(nodes, [e('s1', 't1'), e('t1', 'a1'), e('a1', 's2')]).error).toMatch(/AND bar is wired wrong/i)
  })
})
