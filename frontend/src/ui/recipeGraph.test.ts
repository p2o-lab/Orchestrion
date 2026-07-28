import { describe, expect, it } from 'vitest'
import type { Condition, MasterRecipe, Transition } from '../api/types'
import { graphToTransitions, recipeToGraph, type GraphEdge, type GraphNode } from './recipeGraph'

const step = (id: string, pea = 1, service = 'Stirring', proc = 1): GraphNode => ({
  id, kind: 'step', pea_id: pea, service, procedure_id: proc, params: {},
})
const cond = (state: string, pea = 1, service = 'Stirring'): Condition => ({ type: 'StateReached', pea_id: pea, service, state })

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

describe('AND gateway', () => {
  it('split → one multi-target transition (parallel)', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'a', kind: 'and' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'a', condition: cond('COMPLETED') },
      { source: 'a', target: 's2' },
      { source: 'a', target: 's3' },
    ]
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    expect(transitions).toHaveLength(1)
    expect(transitions[0].from_ids).toEqual(['s1'])
    expect([...transitions[0].to_ids].sort()).toEqual(['s2', 's3'])
  })

  it('merge → one multi-source transition with a single condition', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'a', kind: 'and' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'a' },
      { source: 's2', target: 'a' },
      { source: 'a', target: 's3', condition: cond('EXECUTE') },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect([...transitions[0].from_ids].sort()).toEqual(['s1', 's2'])
    expect(transitions[0].to_ids).toEqual(['s3'])
    expect(transitions[0].condition).toEqual(cond('EXECUTE'))
  })

  it('round-trips an AND split→merge diamond', () => {
    const nodes: GraphNode[] = [
      step('s0'), step('s1'), step('s2'), step('s3'),
      { id: 'a1', kind: 'and' }, { id: 'a2', kind: 'and' }, { id: 'END', kind: 'end' },
    ]
    const edges: GraphEdge[] = [
      { source: 's0', target: 'a1', condition: cond('COMPLETED') },
      { source: 'a1', target: 's1' },
      { source: 'a1', target: 's2' },
      { source: 's1', target: 'a2' },
      { source: 's2', target: 'a2' },
      { source: 'a2', target: 's3', condition: cond('EXECUTE') },
      { source: 's3', target: 'END', condition: cond('COMPLETED') },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const g2 = recipeToGraph(recipeOf(nodes, t1))
    const t2 = graphToTransitions(g2.nodes, g2.edges).transitions
    expect(canon(t2)).toEqual(canon(t1))
  })
})

describe('OR gateway', () => {
  it('split → one transition per branch (selection)', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'o', kind: 'or' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'o' },
      { source: 'o', target: 's2', condition: cond('EXECUTE') },
      { source: 'o', target: 's3', condition: cond('HELD') },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.from_ids[0] === 's1' && t.to_ids.length === 1)).toBe(true)
  })

  it('merge → one transition per branch into the target', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'o', kind: 'or' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'o', condition: cond('EXECUTE') },
      { source: 's2', target: 'o', condition: cond('HELD') },
      { source: 'o', target: 's3' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.to_ids[0] === 's3' && t.from_ids.length === 1)).toBe(true)
  })

  it('round-trips an OR split', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'o', kind: 'or' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'o' },
      { source: 'o', target: 's2', condition: cond('EXECUTE') },
      { source: 'o', target: 's3', condition: cond('HELD') },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const g2 = recipeToGraph(recipeOf(nodes, t1))
    expect(g2.nodes.some((n) => n.kind === 'or')).toBe(true)
    expect(canon(graphToTransitions(g2.nodes, g2.edges).transitions)).toEqual(canon(t1))
  })

  it('round-trips an OR merge', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), { id: 'o', kind: 'or' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'o', condition: cond('EXECUTE') },
      { source: 's2', target: 'o', condition: cond('HELD') },
      { source: 'o', target: 's3' },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const g2 = recipeToGraph(recipeOf(nodes, t1))
    expect(g2.nodes.some((n) => n.kind === 'or')).toBe(true)
    expect(canon(graphToTransitions(g2.nodes, g2.edges).transitions)).toEqual(canon(t1))
  })
})

describe('validation', () => {
  it('rejects a gateway that is both a split and a merge', () => {
    const nodes: GraphNode[] = [step('s1'), step('s2'), step('s3'), step('s4'), { id: 'a', kind: 'and' }]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'a' }, { source: 's2', target: 'a' },
      { source: 'a', target: 's3' }, { source: 'a', target: 's4' },
    ]
    expect(graphToTransitions(nodes, edges).error).toMatch(/split .* or a merge/i)
  })

  it('rejects a dangling gateway', () => {
    const nodes: GraphNode[] = [step('s1'), { id: 'a', kind: 'and' }]
    expect(graphToTransitions(nodes, [{ source: 's1', target: 'a' }]).error).toMatch(/input and one output/i)
  })
})
