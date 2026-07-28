import { describe, expect, it } from 'vitest'
import type { Condition, MasterRecipe, Transition } from '../api/types'
import { graphToTransitions, recipeToGraph, type GraphEdge, type GraphNode } from './recipeGraph'

const step = (id: string, pea = 1, service = 'Stirring', proc = 1): GraphNode => ({
  id, kind: 'step', pea_id: pea, service, procedure_id: proc, params: {},
})
const stateCond = (pea: number, service: string, state: string): Condition => ({
  type: 'StateReached', pea_id: pea, service, state,
})

// Canonicalise for order-independent comparison (nested And/Or sorted too).
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

describe('graphToTransitions', () => {
  it('maps a sequential chain', () => {
    const nodes = [step('s1'), step('s2'), { id: 'END', kind: 'end' } as GraphNode]
    const edges: GraphEdge[] = [
      { source: 's1', target: 's2', condition: stateCond(1, 'Stirring', 'COMPLETED') },
      { source: 's2', target: 'END', condition: stateCond(1, 'Stirring', 'COMPLETED') },
    ]
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    expect(transitions).toHaveLength(2)
    expect(transitions[0]).toMatchObject({ from_ids: ['s1'], to_ids: ['s2'] })
  })

  it('keeps two arrows out of one step as two (selection / OR)', () => {
    const nodes = [step('s1'), step('s2'), step('s3')]
    const edges: GraphEdge[] = [
      { source: 's1', target: 's2', condition: stateCond(1, 'Stirring', 'EXECUTE') },
      { source: 's1', target: 's3', condition: stateCond(1, 'Stirring', 'HELD') },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.from_ids.length === 1 && t.to_ids.length === 1)).toBe(true)
  })

  it('merges a fork into one multi-target transition (AND-split)', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), { id: 'f1', kind: 'fork' } as GraphNode]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'f1' },
      { source: 'f1', target: 's2' },
      { source: 'f1', target: 's3' },
    ]
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    expect(transitions).toHaveLength(1)
    expect(transitions[0].from_ids).toEqual(['s1'])
    expect([...transitions[0].to_ids].sort()).toEqual(['s2', 's3'])
  })

  it('merges a join into one multi-source transition with an AND condition', () => {
    const nodes = [step('s2'), step('s3'), step('s4'), { id: 'j1', kind: 'join', joinState: 'COMPLETED' } as GraphNode]
    const edges: GraphEdge[] = [
      { source: 's2', target: 'j1' },
      { source: 's3', target: 'j1' },
      { source: 'j1', target: 's4' },
    ]
    const { transitions } = graphToTransitions(nodes, edges)
    expect(transitions).toHaveLength(1)
    expect([...transitions[0].from_ids].sort()).toEqual(['s2', 's3'])
    expect(transitions[0].to_ids).toEqual(['s4'])
    expect(transitions[0].condition.type).toBe('And')
  })

  it('rejects a malformed fork (no outputs)', () => {
    const nodes = [step('s1'), { id: 'f1', kind: 'fork' } as GraphNode]
    const { error } = graphToTransitions(nodes, [{ source: 's1', target: 'f1' }])
    expect(error).toMatch(/fork/i)
  })

  it('rejects a malformed join (two outputs)', () => {
    const nodes = [step('s1'), step('s2'), step('s3'), { id: 'j1', kind: 'join' } as GraphNode]
    const edges: GraphEdge[] = [
      { source: 's1', target: 'j1' },
      { source: 'j1', target: 's2' },
      { source: 'j1', target: 's3' },
    ]
    const { error } = graphToTransitions(nodes, edges)
    expect(error).toMatch(/join/i)
  })
})

describe('round-trip (graph → transitions → graph → transitions)', () => {
  it('preserves a fork + join diamond', () => {
    const nodes: GraphNode[] = [
      step('s0'), step('s1'), step('s2'), step('s3'),
      { id: 'f1', kind: 'fork' }, { id: 'j1', kind: 'join', joinState: 'COMPLETED' },
      { id: 'END', kind: 'end' },
    ]
    const edges: GraphEdge[] = [
      { source: 's0', target: 'f1' },
      { source: 'f1', target: 's1' },
      { source: 'f1', target: 's2' },
      { source: 's1', target: 'j1' },
      { source: 's2', target: 'j1' },
      { source: 'j1', target: 's3' },
      { source: 's3', target: 'END', condition: stateCond(1, 'Stirring', 'COMPLETED') },
    ]
    const t1 = graphToTransitions(nodes, edges).transitions
    const recipe: MasterRecipe = {
      header: { name: 'x', version: 1, author: '', product: '' },
      formula: {},
      steps: nodes.filter((n) => n.kind === 'step').map((n) => ({
        id: n.id, pea_id: n.pea_id!, service: n.service!, procedure_id: n.procedure_id!, params: n.params ?? {},
      })),
      transitions: t1,
    }
    const g2 = recipeToGraph(recipe)
    const t2 = graphToTransitions(g2.nodes, g2.edges).transitions
    expect(canon(t2)).toEqual(canon(t1))
  })
})
