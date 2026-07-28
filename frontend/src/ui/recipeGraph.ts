// The recipe builder's graph ⇄ engine-transitions mapping — pure, framework-free, tested.
//
// Node kinds: `step`, `end`, and two gateways — `and` (parallel, two lines) and `or`
// (exclusive/selection, one line). A gateway is a SPLIT when it has one input and many outputs,
// a MERGE when it has many inputs and one output. Engine transition = { from_ids[], to_ids[], condition }.
//
//   AND split  : step →[cond]→ (AND) →→ {B, C}      ⇒ ONE { from:[step], to:[B,C], condition }        (all start together)
//   AND merge  : {B, C} →→ (AND) →[cond]→ D          ⇒ ONE { from:[B,C], to:[D], condition }           (all present + one condition → close all)
//   OR  split  : step → (OR) →→ {B[cB], C[cC]}       ⇒ { from:[step], to:[B], cB } and { …to:[C], cC } (first condition wins)
//   OR  merge  : {B[cB], C[cC]} →→ (OR) → D          ⇒ { from:[B], to:[D], cB } and { from:[C], …, cC } (whichever arrives passes)
//
// The condition lives on the gateway's "single" side: the one input of a split, the one output of
// a merge (AND); or on each branch edge (OR). Plain step→step/end edges carry their own condition.

import type { Condition, MasterRecipe, Transition } from '../api/types'

export const END_ID = 'END'
export type NodeKind = 'step' | 'and' | 'or' | 'end'

export interface GraphNode {
  id: string
  kind: NodeKind
  pea_id?: number
  service?: string
  procedure_id?: number
  params?: Record<string, number>
  x?: number | null
  y?: number | null
}

export interface GraphEdge {
  source: string
  target: string
  condition?: Condition
}

const completedFor = (n: GraphNode | undefined): Condition => ({
  type: 'StateReached',
  pea_id: n?.pea_id ?? 0,
  service: n?.service ?? '',
  state: 'COMPLETED',
})

/** Canvas graph → engine transitions. Returns an error message if a gateway is malformed. */
export function graphToTransitions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { transitions: Transition[]; error: string | null } {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const isGate = (id: string) => byId.get(id)?.kind === 'and' || byId.get(id)?.kind === 'or'
  const transitions: Transition[] = []

  for (const g of nodes.filter((n) => n.kind === 'and' || n.kind === 'or')) {
    const ins = edges.filter((e) => e.target === g.id)
    const outs = edges.filter((e) => e.source === g.id)
    const label = g.kind === 'and' ? 'An AND gateway' : 'An OR gateway'
    if (ins.length === 0 || outs.length === 0)
      return { transitions: [], error: `${label} needs at least one input and one output.` }
    const split = ins.length === 1
    const merge = outs.length === 1
    if (!split && !merge)
      return { transitions: [], error: `${label} must be a split (1→many) or a merge (many→1), not both.` }

    if (g.kind === 'and') {
      if (split) {
        transitions.push({
          from_ids: [ins[0].source],
          to_ids: outs.map((o) => o.target),
          condition: ins[0].condition ?? completedFor(byId.get(ins[0].source)),
        })
      } else {
        transitions.push({
          from_ids: ins.map((i) => i.source),
          to_ids: [outs[0].target],
          condition: outs[0].condition ?? completedFor(byId.get(ins[0].source)),
        })
      }
    } else {
      // OR: one transition per branch.
      if (split) {
        for (const o of outs)
          transitions.push({ from_ids: [ins[0].source], to_ids: [o.target], condition: o.condition ?? completedFor(byId.get(ins[0].source)) })
      } else {
        for (const i of ins)
          transitions.push({ from_ids: [i.source], to_ids: [outs[0].target], condition: i.condition ?? completedFor(byId.get(i.source)) })
      }
    }
  }

  for (const e of edges) {
    if (isGate(e.source) || isGate(e.target)) continue
    transitions.push({ from_ids: [e.source], to_ids: [e.target], condition: e.condition ?? completedFor(byId.get(e.source)) })
  }

  return { transitions, error: null }
}

/** Engine transitions → canvas graph (reconstruct gateways). */
export function recipeToGraph(recipe: MasterRecipe): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = recipe.steps.map((s) => ({
    id: s.id, kind: 'step', pea_id: s.pea_id, service: s.service, procedure_id: s.procedure_id, params: s.params, x: s.x, y: s.y,
  }))
  nodes.push({ id: END_ID, kind: 'end' })
  const edges: GraphEdge[] = []
  let gid = 0
  const newGate = (kind: 'and' | 'or') => {
    const id = `${kind}-${++gid}`
    nodes.push({ id, kind })
    return id
  }

  const singles = recipe.transitions.filter((t) => t.from_ids.length === 1 && t.to_ids.length === 1)
  const used = new Set<Transition>()

  // AND split (1→many) and AND merge (many→1).
  for (const t of recipe.transitions) {
    if (t.from_ids.length === 1 && t.to_ids.length > 1) {
      const g = newGate('and')
      edges.push({ source: t.from_ids[0], target: g, condition: t.condition })
      t.to_ids.forEach((to) => edges.push({ source: g, target: to }))
    } else if (t.from_ids.length > 1 && t.to_ids.length === 1) {
      const g = newGate('and')
      t.from_ids.forEach((f) => edges.push({ source: f, target: g }))
      edges.push({ source: g, target: t.to_ids[0], condition: t.condition })
    } else if (t.from_ids.length > 1 && t.to_ids.length > 1) {
      t.from_ids.forEach((f) => t.to_ids.forEach((to) => edges.push({ source: f, target: to, condition: t.condition })))
    }
  }

  // OR split: several single 1→1 transitions sharing a source.
  const byFrom = new Map<string, Transition[]>()
  for (const t of singles) (byFrom.get(t.from_ids[0]) ?? byFrom.set(t.from_ids[0], []).get(t.from_ids[0])!).push(t)
  for (const [from, ts] of byFrom) {
    if (ts.length >= 2) {
      const g = newGate('or')
      edges.push({ source: from, target: g })
      ts.forEach((t) => { edges.push({ source: g, target: t.to_ids[0], condition: t.condition }); used.add(t) })
    }
  }

  // OR merge: remaining singles sharing a target.
  const rest = singles.filter((t) => !used.has(t))
  const byTo = new Map<string, Transition[]>()
  for (const t of rest) (byTo.get(t.to_ids[0]) ?? byTo.set(t.to_ids[0], []).get(t.to_ids[0])!).push(t)
  for (const [to, ts] of byTo) {
    if (ts.length >= 2) {
      const g = newGate('or')
      ts.forEach((t) => { edges.push({ source: t.from_ids[0], target: g, condition: t.condition }); used.add(t) })
      edges.push({ source: g, target: to })
    }
  }

  // Lone 1→1 transitions become plain edges.
  for (const t of rest) if (!used.has(t)) edges.push({ source: t.from_ids[0], target: t.to_ids[0], condition: t.condition })

  return { nodes, edges }
}
