import { describe, expect, it } from 'vitest'
import type { Condition, MasterRecipe, Transition } from '../api/types'
import { graphToTransitions, recipeToGraph, START_ID, END_ID, type GraphEdge, type GraphNode } from './recipeGraph'

const step = (id: string, pea = 1, service = 'Stirring', proc = 1): GraphNode => ({
  id, kind: 'step', pea_id: pea, service, procedure_id: proc, params: {},
})
const cond = (state: string, pea = 1, service = 'Stirring'): Condition => ({ type: 'StateReached', pea_id: pea, service, state })
const trans = (id: string, condition?: Condition): GraphNode => ({ id, kind: 'transition', condition })

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

describe('GRAFCET series', () => {
  it('start → s1 → T → s2 → T → END', () => {
    const nodes: GraphNode[] = [
      { id: START_ID, kind: 'start' }, step('s1'), step('s2'), { id: END_ID, kind: 'end' },
      trans('t1', cond('COMPLETED')), trans('t2', cond('COMPLETED', 2)),
    ]
    const edges: GraphEdge[] = [
      { source: START_ID, target: 's1' },
      { source: 's1', target: 't1' }, { source: 't1', target: 's2' },
      { source: 's2', target: 't2' }, { source: 't2', target: END_ID },
    ]
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    expect(canon(transitions)).toEqual(canon([
      { from_ids: ['s1'], to_ids: ['s2'], condition: cond('COMPLETED') },
      { from_ids: ['s2'], to_ids: [END_ID], condition: cond('COMPLETED', 2) },
    ]))
  })

  it('defaults a bare transition to source ✓ COMPLETED', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), trans('t1')]
    const edges: GraphEdge[] = [{ source: 's1', target: 't1' }, { source: 't1', target: 's2' }]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions[0].condition).toEqual(cond('COMPLETED'))
  })
})

describe('AND (simultaneous) — one transition, many branches', () => {
  it('divergence → one multi-target transition', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), trans('t1', cond('COMPLETED'))]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 't1', target: 's2' }, { source: 't1', target: 's3' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect(transitions[0].from_ids).toEqual(['s1'])
    expect([...transitions[0].to_ids].sort()).toEqual(['s2', 's3'])
  })

  it('convergence → one multi-source transition (join)', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), trans('t1', cond('EXECUTE'))]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 's2', target: 't1' }, { source: 't1', target: 's3' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect([...transitions[0].from_ids].sort()).toEqual(['s1', 's2'])
    expect(transitions[0].to_ids).toEqual(['s3'])
    expect(transitions[0].condition).toEqual(cond('EXECUTE'))
  })

  it('round-trips an AND split→join diamond', () => {
    const nodes: GraphNode[] = [
      step('s0'), step('s1'), step('s2'), step('s3'),
      trans('t1', cond('COMPLETED')), trans('t2', cond('EXECUTE')), trans('t3', cond('COMPLETED', 3)),
      { id: END_ID, kind: 'end' }, { id: START_ID, kind: 'start' },
    ]
    const edges: GraphEdge[] = [
      { source: START_ID, target: 's0' },
      { source: 's0', target: 't1' }, { source: 't1', target: 's1' }, { source: 't1', target: 's2' },
      { source: 's1', target: 't2' }, { source: 's2', target: 't2' }, { source: 't2', target: 's3' },
      { source: 's3', target: 't3' }, { source: 't3', target: END_ID },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const g2 = recipeToGraph(recipeOf(nodes, t1))
    const t2 = graphToTransitions(g2.nodes, g2.edges).transitions
    expect(canon(t2)).toEqual(canon(t1))
  })
})

describe('OR (selection) — many transitions from/into one step', () => {
  it('divergence → one transition per branch', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), trans('t1', cond('EXECUTE')), trans('t2', cond('HELD'))]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 't1', target: 's2' },
      { source: 's1', target: 't2' }, { source: 't2', target: 's3' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.from_ids[0] === 's1' && t.to_ids.length === 1)).toBe(true)
  })

  it('convergence → one transition per branch into the target', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), trans('t1', cond('COMPLETED')), trans('t2', cond('COMPLETED', 2))]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 't1', target: 's3' },
      { source: 's2', target: 't2' }, { source: 't2', target: 's3' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.to_ids[0] === 's3' && t.from_ids.length === 1)).toBe(true)
  })

  it('round-trips an OR divergence', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), trans('t1', cond('EXECUTE')), trans('t2', cond('HELD'))]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 't1', target: 's2' },
      { source: 's1', target: 't2' }, { source: 't2', target: 's3' },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const g2 = recipeToGraph(recipeOf(nodes, t1))
    expect(canon(graphToTransitions(g2.nodes, g2.edges).transitions)).toEqual(canon(t1))
  })
})

describe('GRAFCET alternation rules', () => {
  it('rejects a step wired straight to another step', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2')]
    expect(graphToTransitions(nodes, [{ source: 's1', target: 's2' }]).error).toMatch(/alternates steps and transitions/i)
  })

  it('rejects two transitions wired together', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), trans('t1'), trans('t2')]
    const edges: GraphEdge[] = [
      { source: 's1', target: 't1' }, { source: 't1', target: 't2' }, { source: 't2', target: 's2' },
    ]
    expect(graphToTransitions(nodes, edges).error).toMatch(/alternates steps and transitions/i)
  })

  it('rejects a dangling transition (no step before or after)', () => {
    const nodes: GraphNode[] = [step('s1'), trans('t1')]
    expect(graphToTransitions(nodes, [{ source: 's1', target: 't1' }]).error).toMatch(/before it and one after/i)
  })
})
