// The recipe builder's GRAFCET graph ⇄ engine-transitions mapping — pure, framework-free, tested.
//
// GRAFCET (IEC 60848 — the notation IEC 61512-1:2023 normatively references: its reference list +
// §5.3.1 Note 2). A chart is a strict alternation of STEPS and TRANSITIONS joined by directed links:
//   • a step-like node (start | step | end) links only to a transition, and a transition links only
//     to a step-like node — never step→step or transition→transition (the alternation rule).
//   • the INITIAL step (the `start` marker points straight to it) is active when the recipe begins;
//     it has no preceding transition. A transition → `end` finishes that branch.
//   • a TRANSITION carries the receptivity (our `Condition`) — the guard lives on the transition,
//     NOT on the arrow. It fires when all its upstream steps are active and the condition is true,
//     deactivating them and activating all its downstream steps.
//
// Each transition node ⇒ exactly one engine `Transition { from_ids, to_ids, condition }`:
//   series          s1 → T → s2            { from:[s1], to:[s2] }
//   AND divergence  s1 → T → {s2,s3}       { from:[s1], to:[s2,s3] }          (one T, many out — simultaneous)
//   AND convergence {s2,s3} → T → s4       { from:[s2,s3], to:[s4] }          (one T, many in — join)
//   OR  divergence  s1 → {T1→s2, T2→s3}    two T: {[s1],[s2]}, {[s1],[s3]}    (many T from one step — selection)
//   OR  convergence {s2→T1, s3→T2} → s4    two T: {[s2],[s4]}, {[s3],[s4]}
// AND vs OR is not a node type — it falls out of WHERE the branch is: after a transition = simultaneous,
// before the transitions (a step with several) = selection. [IEC 61512-1:2023 §5.3.1: "a procedure
// consists of a set of steps in series, in parallel, or a combination of both. Transition conditions
// may be inserted between any steps to modify which steps will execute… Steps are initiated only after
// the immediate predecessor(s) in series with them have completed and any intervening transition
// conditions are true."]

import type { Condition, MasterRecipe, Transition } from '../api/types'

export const START_ID = 'START'
export const END_ID = 'END'
export type NodeKind = 'start' | 'step' | 'transition' | 'end'

export interface GraphNode {
  id: string
  kind: NodeKind
  // step fields
  pea_id?: number
  service?: string
  procedure_id?: number
  params?: Record<string, number>
  // transition field — the receptivity guard
  condition?: Condition
  // UI-only canvas position
  x?: number | null
  y?: number | null
}

export interface GraphEdge {
  source: string
  target: string
}

const isStepLike = (k: NodeKind | undefined) => k === 'start' || k === 'step' || k === 'end'

const completedFor = (n: GraphNode | undefined): Condition => ({
  type: 'StateReached',
  pea_id: n?.pea_id ?? 0,
  service: n?.service ?? '',
  state: 'COMPLETED',
})

/** GRAFCET canvas graph → engine transitions. Returns an error message if the chart breaks a rule. */
export function graphToTransitions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { transitions: Transition[]; error: string | null } {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const kindOf = (id: string) => byId.get(id)?.kind

  // 1. Every link obeys the alternation rule.
  for (const e of edges) {
    const s = kindOf(e.source)
    const t = kindOf(e.target)
    if (!s || !t) return { transitions: [], error: `A link references a node that no longer exists.` }
    if (s === 'end') return { transitions: [], error: `Nothing may follow END.` }
    if (t === 'start') return { transitions: [], error: `Nothing may lead into START.` }
    if (s === 'start') {
      // START marks the initial step: it links straight to a step, never to a transition.
      if (t !== 'step') return { transitions: [], error: `START must connect directly to a step (the initial step).` }
      continue
    }
    const ok = (isStepLike(s) && t === 'transition') || (s === 'transition' && isStepLike(t))
    if (!ok)
      return {
        transitions: [],
        error: `GRAFCET alternates steps and transitions: a ${s} cannot link to a ${t}. Put a transition between two steps.`,
      }
  }

  // 2. Each transition node becomes exactly one engine transition.
  const transitions: Transition[] = []
  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const from = edges.filter((e) => e.target === tr.id).map((e) => e.source)
    const to = edges.filter((e) => e.source === tr.id).map((e) => e.target)
    if (from.length === 0 || to.length === 0)
      return { transitions: [], error: `Every transition needs at least one step before it and one after it.` }
    transitions.push({
      from_ids: from,
      to_ids: to,
      condition: tr.condition ?? completedFor(byId.get(from[0])),
    })
  }

  return { transitions, error: null }
}

/** Engine transitions → GRAFCET canvas graph (transitions become nodes; START marks initial steps). */
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
  nodes.push({ id: START_ID, kind: 'start' })
  nodes.push({ id: END_ID, kind: 'end' })

  const edges: GraphEdge[] = []
  recipe.transitions.forEach((t, i) => {
    const tid = `t${i + 1}`
    nodes.push({ id: tid, kind: 'transition', condition: t.condition })
    t.from_ids.forEach((f) => edges.push({ source: f, target: tid }))
    t.to_ids.forEach((to) => edges.push({ source: tid, target: to }))
  })

  // The initial steps are those no transition ever targets — wire START straight to each.
  const targeted = new Set(recipe.transitions.flatMap((t) => t.to_ids))
  for (const s of recipe.steps) if (!targeted.has(s.id)) edges.push({ source: START_ID, target: s.id })

  return { nodes, edges }
}
