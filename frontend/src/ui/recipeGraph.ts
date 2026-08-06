// The recipe builder's GRAFCET graph ⇄ engine-transitions mapping — pure, framework-free, tested.
//
// GRAFCET (IEC 60848 — the notation IEC 61512-1:2023 normatively references). A chart alternates
// STEPS and TRANSITIONS joined by directed links, with two branch junctions:
//   • TRANSITION — carries the receptivity (our `Condition`). The guard lives here, never on an edge.
//   • AND bar (═, "divergence/convergence en ET") — SIMULTANEOUS. One transition splits into several
//     parallel steps (divergence), or several steps synchronise into one transition (convergence).
//     Carries NO condition.
//   • OR bar (─, "divergence/convergence en OU") — SELECTION. One step opens onto several branch
//     transitions (divergence), or several branch transitions merge into one step (convergence).
//     Carries NO condition.
//   • START marks the initial step; END finishes a branch.
//
// Placement (the alternation, with the bars):
//   series        s1 → T → s2
//   AND diverge   s1 → T → ═ → {s2, s3}          (one transition, the double bar, parallel steps)
//   AND converge  {s1, s2} → ═ → T → s3          (parallel steps, the double bar, one transition)
//   OR  diverge   s1 → ─ → {T→s2, T→s3}          (one step, the single bar, a transition per branch)
//   OR  converge  {s1→T, s2→T} → ─ → s3          (a transition per branch, the single bar, one step)
//
// Each TRANSITION node ⇒ exactly one engine `Transition { from_ids, to_ids, condition }`. The bars
// carry no transition of their own; a transition resolves its from/to ONE HOP through an adjacent bar
// to the real steps (or END). [IEC 61512-1:2023 §5.3.1: a procedure is steps in series/parallel with
// transition conditions inserted between them; a step starts only once its predecessors have completed
// and the intervening transition condition is true.]

import type { Condition, MasterRecipe, Transition } from '../api/types'

export const START_ID = 'START'
export const END_ID = 'END'
export type NodeKind = 'start' | 'step' | 'transition' | 'and' | 'or' | 'end'

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

// Which source-kind → target-kind links are legal (the GRAFCET alternation, with the AND/OR bars).
const ALLOWED: Record<NodeKind, Set<NodeKind>> = {
  start: new Set<NodeKind>(['step']),
  step: new Set<NodeKind>(['transition', 'and', 'or']),
  transition: new Set<NodeKind>(['step', 'and', 'or', 'end']),
  and: new Set<NodeKind>(['step', 'transition']),
  or: new Set<NodeKind>(['step', 'transition']),
  end: new Set<NodeKind>([]),
}

const completedFor = (n: GraphNode | undefined): Condition => ({
  type: 'StateReached',
  pea_id: n?.pea_id ?? 0,
  service: n?.service ?? '',
  state: 'COMPLETED',
})

const uniq = (xs: string[]) => [...new Set(xs)]

/** GRAFCET canvas graph → engine transitions. Returns an error message if the chart breaks a rule. */
export function graphToTransitions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { transitions: Transition[]; error: string | null } {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const kindOf = (id: string) => byId.get(id)?.kind
  const outOf = (id: string) => edges.filter((e) => e.source === id).map((e) => e.target)
  const intoOf = (id: string) => edges.filter((e) => e.target === id).map((e) => e.source)

  // 1. Every link obeys the alternation rule.
  for (const e of edges) {
    const s = kindOf(e.source)
    const t = kindOf(e.target)
    if (!s || !t) return { transitions: [], error: `A link references a node that no longer exists.` }
    if (!ALLOWED[s].has(t))
      return {
        transitions: [],
        error: `GRAFCET alternates steps and transitions: a ${s} cannot link to a ${t}. Put a transition (or an AND/OR bar) between them.`,
      }
  }

  // 2. Every AND/OR bar is a valid divergence XOR convergence. A bar has a "single" side (AND: one
  //    transition · OR: one step) and a "many" side of ≥2 branches (AND: parallel steps · OR: branch
  //    transitions). This rejects both step→bar→step (no transition) and a pointless one-branch bar.
  for (const bar of nodes.filter((n) => n.kind === 'and' || n.kind === 'or')) {
    const insK = intoOf(bar.id).map(kindOf)
    const outsK = outOf(bar.id).map(kindOf)
    const single: NodeKind = bar.kind === 'and' ? 'transition' : 'step'
    const many: NodeKind = bar.kind === 'and' ? 'step' : 'transition'
    const diverge = insK.length === 1 && insK[0] === single && outsK.length >= 2 && outsK.every((k) => k === many)
    const converge = outsK.length === 1 && outsK[0] === single && insK.length >= 2 && insK.every((k) => k === many)
    if (!diverge && !converge) {
      const shape =
        bar.kind === 'and'
          ? 'an AND joins one transition on one side and ≥2 parallel steps on the other'
          : 'an OR joins one step on one side and ≥2 branch transitions on the other'
      return { transitions: [], error: `This ${bar.kind.toUpperCase()} bar is wired wrong — ${shape}.` }
    }
  }

  // A transition reaches its real from/to steps one hop through an adjacent AND/OR bar.
  const resolveFrom = (id: string): string[] => {
    const k = kindOf(id)
    return k === 'and' || k === 'or' ? intoOf(id) : [id] // step, or steps feeding the bar
  }
  const resolveTo = (id: string): string[] => {
    const k = kindOf(id)
    return k === 'and' || k === 'or' ? outOf(id) : [id] // step/END, or steps the bar opens onto
  }

  // 2. Each transition node becomes exactly one engine transition.
  const transitions: Transition[] = []
  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const from = uniq(intoOf(tr.id).flatMap(resolveFrom))
    const to = uniq(outOf(tr.id).flatMap(resolveTo))
    if (from.length === 0 || to.length === 0)
      return { transitions: [], error: `Every transition needs at least one step before it and one after it.` }
    transitions.push({ from_ids: from, to_ids: to, condition: tr.condition ?? completedFor(byId.get(from[0])) })
  }

  return { transitions, error: null }
}

/** Engine transitions → GRAFCET canvas graph (rebuild transitions + AND/OR bars; START marks initial). */
export function recipeToGraph(recipe: MasterRecipe): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = recipe.steps.map((s) => ({
    id: s.id, kind: 'step', pea_id: s.pea_id, service: s.service, procedure_id: s.procedure_id, params: s.params, x: s.x, y: s.y,
  }))
  nodes.push({ id: START_ID, kind: 'start' })
  nodes.push({ id: END_ID, kind: 'end' })
  const edges: GraphEdge[] = []

  let tc = 0
  let ac = 0
  let oc = 0
  const newTransition = (condition: Condition) => {
    const id = `t${++tc}`
    nodes.push({ id, kind: 'transition', condition })
    return id
  }
  const newBar = (kind: 'and' | 'or') => {
    const id = kind === 'and' ? `and${++ac}` : `or${++oc}`
    nodes.push({ id, kind })
    return id
  }

  // OR groups: several single-from transitions off one step = OR divergence; several single-to
  // transitions into one step = OR convergence. Count only among single-ended transitions.
  const fromCount = new Map<string, number>()
  const toCount = new Map<string, number>()
  for (const t of recipe.transitions) {
    if (t.from_ids.length === 1) fromCount.set(t.from_ids[0], (fromCount.get(t.from_ids[0]) ?? 0) + 1)
    if (t.to_ids.length === 1) toCount.set(t.to_ids[0], (toCount.get(t.to_ids[0]) ?? 0) + 1)
  }
  const orDiv = new Map<string, string>() // from-step → shared OR bar
  const orConv = new Map<string, string>() // to-step → shared OR bar

  for (const t of recipe.transitions) {
    const T = newTransition(t.condition)

    // ── from side ──
    if (t.from_ids.length > 1) {
      const bar = newBar('and') // AND convergence
      t.from_ids.forEach((f) => edges.push({ source: f, target: bar }))
      edges.push({ source: bar, target: T })
    } else {
      const f = t.from_ids[0]
      if ((fromCount.get(f) ?? 0) >= 2) {
        let bar = orDiv.get(f)
        if (!bar) { bar = newBar('or'); orDiv.set(f, bar); edges.push({ source: f, target: bar }) }
        edges.push({ source: bar, target: T })
      } else {
        edges.push({ source: f, target: T })
      }
    }

    // ── to side ──
    if (t.to_ids.length > 1) {
      const bar = newBar('and') // AND divergence
      edges.push({ source: T, target: bar })
      t.to_ids.forEach((to) => edges.push({ source: bar, target: to }))
    } else {
      const to = t.to_ids[0]
      if ((toCount.get(to) ?? 0) >= 2) {
        let bar = orConv.get(to)
        if (!bar) { bar = newBar('or'); orConv.set(to, bar); edges.push({ source: bar, target: to }) }
        edges.push({ source: T, target: bar })
      } else {
        edges.push({ source: T, target: to })
      }
    }
  }

  // Initial steps = those no transition ever targets — wire START straight to each.
  const targeted = new Set(recipe.transitions.flatMap((t) => t.to_ids))
  for (const s of recipe.steps) if (!targeted.has(s.id)) edges.push({ source: START_ID, target: s.id })

  return { nodes, edges }
}
