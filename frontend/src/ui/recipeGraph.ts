// The recipe builder's graph ⇄ engine-transitions mapping — pure, framework-free, tested.
//
// The canvas has four node kinds: `step`, `fork` (AND-split), `join` (AND-convergence), `end`.
// The engine transition is `{ from_ids[], to_ids[], condition }` (fire = all `from` finish, all
// `to` start). The four SFC branch forms map like this:
//   • sequential / selection (OR) : a plain step→step edge = one single-from/to transition.
//   • AND-split  (fork)  : step →[cond]→ FORK →→ {B, C}  ⇒ { from:[step], to:[B,C], condition }.
//   • AND-join   (join)  : {B, C} →→ JOIN →→ D           ⇒ { from:[B,C], to:[D], condition: AND(branches reached joinState) }.
// Conditions live on: plain step→step edges, and the single step→fork edge. Fork→x and x→join
// and join→x edges carry no condition (the join's guard is derived from its `joinState`).

import type { Condition, MasterRecipe, Transition } from '../api/types'

export const END_ID = 'END'
export type NodeKind = 'step' | 'fork' | 'join' | 'end'

export interface GraphNode {
  id: string
  kind: NodeKind
  // step-only
  pea_id?: number
  service?: string
  procedure_id?: number
  params?: Record<string, number>
  x?: number | null
  y?: number | null
  // join-only: the state every incoming branch must reach (default COMPLETED)
  joinState?: string
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

const reached = (n: GraphNode | undefined, state: string): Condition => ({
  type: 'StateReached',
  pea_id: n?.pea_id ?? 0,
  service: n?.service ?? '',
  state,
})

/** Canvas graph → engine transitions. Returns an error message if a fork/join is malformed. */
export function graphToTransitions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { transitions: Transition[]; error: string | null } {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const kindOf = (id: string) => byId.get(id)?.kind
  const transitions: Transition[] = []

  for (const f of nodes.filter((n) => n.kind === 'fork')) {
    const ins = edges.filter((e) => e.target === f.id)
    const outs = edges.filter((e) => e.source === f.id)
    if (ins.length !== 1)
      return { transitions: [], error: `A fork needs exactly one incoming arrow (has ${ins.length}).` }
    if (outs.length < 1) return { transitions: [], error: 'A fork needs at least one outgoing branch.' }
    transitions.push({
      from_ids: [ins[0].source],
      to_ids: outs.map((o) => o.target),
      condition: ins[0].condition ?? completedFor(byId.get(ins[0].source)),
    })
  }

  for (const j of nodes.filter((n) => n.kind === 'join')) {
    const ins = edges.filter((e) => e.target === j.id)
    const outs = edges.filter((e) => e.source === j.id)
    if (outs.length !== 1)
      return { transitions: [], error: `A join needs exactly one outgoing arrow (has ${outs.length}).` }
    if (ins.length < 1) return { transitions: [], error: 'A join needs at least one incoming branch.' }
    const state = j.joinState ?? 'COMPLETED'
    const subs = ins.map((i) => reached(byId.get(i.source), state))
    transitions.push({
      from_ids: ins.map((i) => i.source),
      to_ids: [outs[0].target],
      condition: subs.length === 1 ? subs[0] : { type: 'And', conditions: subs },
    })
  }

  for (const e of edges) {
    if (kindOf(e.source) === 'fork' || kindOf(e.source) === 'join') continue
    if (kindOf(e.target) === 'fork' || kindOf(e.target) === 'join') continue
    transitions.push({
      from_ids: [e.source],
      to_ids: [e.target],
      condition: e.condition ?? completedFor(byId.get(e.source)),
    })
  }

  return { transitions, error: null }
}

function joinStateOf(c: Condition): string {
  if (c.type === 'StateReached') return c.state
  if (c.type === 'And') {
    const first = c.conditions.find((x) => x.type === 'StateReached')
    if (first && first.type === 'StateReached') return first.state
  }
  return 'COMPLETED'
}

/** Engine transitions → canvas graph (reconstruct fork/join from multi to/from). */
export function recipeToGraph(recipe: MasterRecipe): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = recipe.steps.map((s) => ({
    id: s.id,
    kind: 'step',
    pea_id: s.pea_id,
    service: s.service,
    procedure_id: s.procedure_id,
    params: s.params,
    x: s.x,
    y: s.y,
  }))
  nodes.push({ id: END_ID, kind: 'end' })
  const edges: GraphEdge[] = []
  let forkN = 0
  let joinN = 0

  for (const t of recipe.transitions) {
    const nFrom = t.from_ids.length
    const nTo = t.to_ids.length
    if (nFrom === 1 && nTo === 1) {
      edges.push({ source: t.from_ids[0], target: t.to_ids[0], condition: t.condition })
    } else if (nFrom === 1 && nTo > 1) {
      const fid = `fork-${++forkN}`
      nodes.push({ id: fid, kind: 'fork' })
      edges.push({ source: t.from_ids[0], target: fid, condition: t.condition })
      t.to_ids.forEach((to) => edges.push({ source: fid, target: to }))
    } else if (nFrom > 1 && nTo === 1) {
      const jid = `join-${++joinN}`
      nodes.push({ id: jid, kind: 'join', joinState: joinStateOf(t.condition) })
      t.from_ids.forEach((from) => edges.push({ source: from, target: jid }))
      edges.push({ source: jid, target: t.to_ids[0] })
    } else {
      // from>1 AND to>1 — the builder never produces this; keep connectivity as direct edges.
      t.from_ids.forEach((from) =>
        t.to_ids.forEach((to) => edges.push({ source: from, target: to, condition: t.condition })),
      )
    }
  }
  return { nodes, edges }
}
