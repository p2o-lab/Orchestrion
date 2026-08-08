// The recipe chart's canvas-graph ⇄ engine-transitions mapping — pure, framework-free, tested.
//
// Authority: `docs/POL_Recipe_Chart_GRAFCET.md`. Read §0a first — **GRAFCET (IEC 60848) is a
// borrowed notation; ISA-88 (IEC 61512-1) is the conformance target.** Where GRAFCET is looser
// (cycles, several initial steps), ISA-88 wins.
//
// ── TWO NODE KINDS. NOTHING ELSE. ────────────────────────────────────────────────────────
// §4.3.2 "The structure comprises the following basic items": step · transition · directed link.
// §4.3.3 adds transition-condition and action. That list is closed, so the canvas holds
//   • STEP       — a phase: one PEA service procedure to run
//   • TRANSITION — a node carrying the receptivity (§4.3.3: "associated with each transition,
//                  the transition-condition is a logical expression which is true or false")
// and directed links, which carry nothing (§3.1.2).
//
// **No START node. No END node. No AND node. No OR node.** All four were modelled as graph
// elements by earlier builders and all four are wrong:
//   • AND/OR are **link multiplicity**, not elements — §4.3.2: "a directed link connects one or
//     several steps to a transition, or a transition to one or several steps". The bars are how
//     you *draw* that; drawing conventions are unit 10's job, not the model's.
//   • the initial step is **inferred from topology** (§2) and drawn with a double border;
//   • the end of a branch is an **unwired transition output** (§3, a "pit transition"),
//     serialised as the `END` sentinel.
//
// ── THE FOUR BRANCH FORMS, ALL FROM LINK COUNT ───────────────────────────────────────────
//   series          s1 → T → s2
//   AND divergence  s1 → T → {s2, s3}     one transition, several succeeding steps
//   AND convergence {s1, s2} → T → s3     several preceding steps, one transition
//   OR  divergence  s1 → {T1 → s2, T2 → s3}   one step, several succeeding transitions
//   OR  convergence {s1 → T1, s2 → T2} → s3   several transitions into one step
//
// Each TRANSITION node ⇒ exactly one engine `Transition {from_ids, to_ids, condition}`. 1:1, no
// heuristics — which is what the bar-node model could never manage.

import type { Condition, MasterRecipe, RecipeStep, Transition } from '../api/types'

/** The engine's "this branch is finished" sentinel (`recipe/model.py:40`). Never a node. */
export const END_ID = 'END'

export type NodeKind = 'step' | 'transition'

export interface GraphNode {
  id: string
  kind: NodeKind
  /** step only — the phase binding */
  pea_id?: number
  service?: string
  procedure_id?: number
  params?: Record<string, number>
  /** step only — persisted canvas position (`model.py:72-73`, UI-only, non-normative).
   *  Transitions deliberately have none: a transition's place is a *function* of its
   *  neighbours (§9), so it is computed, never stored. */
  x?: number | null
  y?: number | null
  /** transition only — the receptivity */
  condition?: Condition
}

export interface GraphEdge {
  source: string
  target: string
}

/** The alternation rule — §4.4: "Step transition and transition step alternation **shall**
 *  always be respected whatever the sequence." With the bars gone this is the whole table. */
const ALLOWED: Record<NodeKind, NodeKind> = {
  step: 'transition',
  transition: 'step',
}

const uniq = (xs: string[]) => [...new Set(xs)]

// ── mapping ───────────────────────────────────────────────────────────────────────────────

/**
 * Canvas graph → engine transitions.
 *
 * Returns `error` (and no transitions) if the chart breaks a structural rule. Only the rules
 * *inherent to mapping* live here — alternation, dangling links, a transition with no
 * predecessor. The wider rule set (one initial step, no cycles, `Always` on a continuous
 * step) is unit 12's, and is enforced server-side regardless: a recipe can be POSTed straight
 * past this builder, so the canvas is an authoring aid, never the safety boundary.
 */
export function graphToTransitions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { transitions: Transition[]; error: string | null } {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const outOf = (id: string) => edges.filter((e) => e.source === id).map((e) => e.target)
  const intoOf = (id: string) => edges.filter((e) => e.target === id).map((e) => e.source)

  for (const e of edges) {
    const source = byId.get(e.source)
    const target = byId.get(e.target)
    if (!source || !target)
      return { transitions: [], error: 'A link references a node that no longer exists.' }
    if (ALLOWED[source.kind] !== target.kind)
      return {
        transitions: [],
        error:
          `GRAFCET alternates steps and transitions: a ${source.kind} cannot link straight to ` +
          `a ${target.kind}. Put a ${ALLOWED[source.kind]} between them.`,
      }
  }

  const transitions: Transition[] = []
  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const from = uniq(intoOf(tr.id))
    if (from.length === 0)
      return {
        transitions: [],
        error: 'Every transition needs at least one step before it.',
      }
    // §3 — an unwired output **is** the end of the branch. No toggle, no gesture: a pit
    // transition simply has no successor, and that serialises as the END sentinel.
    const to = uniq(outOf(tr.id))
    transitions.push({
      from_ids: from,
      to_ids: to.length > 0 ? to : [END_ID],
      condition: tr.condition ?? { type: 'Always' },
    })
  }
  return { transitions, error: null }
}

/** Engine transitions → canvas graph. One transition node per engine transition, 1:1. */
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
  const edges: GraphEdge[] = []

  recipe.transitions.forEach((t, i) => {
    const id = `t${i + 1}`
    nodes.push({ id, kind: 'transition', condition: t.condition })
    t.from_ids.forEach((f) => edges.push({ source: f, target: id }))
    // END is a sentinel, not a node — a branch that ends simply leaves the output unwired,
    // and the canvas draws that as a cap (§3).
    t.to_ids.filter((to) => to !== END_ID).forEach((to) => edges.push({ source: id, target: to }))
  })

  return { nodes, edges }
}

// ── pure helpers the canvas needs (extracted so they can be tested at all) ─────────────────

/**
 * The initial step — §2, and [IEC 61512-1] item 1337: a procedure has *"a defined beginning
 * and end"*, **singular**.
 *
 * Inferred from topology: the one step no transition targets. `null` when there is not
 * exactly one, so the caller can warn while building and block on save.
 *
 * ⚠ The inference is only sound because **cycles are rejected** (§2/§10). IEC 60848's own
 * Figure 2 is a cycle whose double-bordered initial step *is* a transition target — run this
 * over it and you get none. That is a deliberate ISA-88 narrowing, not a GRAFCET claim.
 */
export function initialStepId(nodes: GraphNode[], edges: GraphEdge[]): string | null {
  const targeted = new Set(edges.map((e) => e.target))
  const initial = nodes.filter((n) => n.kind === 'step' && !targeted.has(n.id))
  return initial.length === 1 ? initial[0].id : null
}

/** A transition with no outgoing link — its branch ends here (§3, "pit transition"). */
export function isPitTransition(id: string, edges: GraphEdge[]): boolean {
  return !edges.some((e) => e.source === id)
}

/**
 * The receptivity a newly-wired transition should start with — §4.
 *
 * `Always` when every preceding step ends by itself: completion is gate #1 (step model §3), so
 * the author has nothing to add. **`null` when any preceding step is continuous** — there the
 * receptivity *is* the completion criterion, so `Always` would start the service and complete
 * it in the same instant. The caller must make the author supply a real one.
 *
 * Stated over *all* the from-steps, not one, because a continuous step may also feed an
 * AND-join (§5(b)) — which is exactly where `=1` would otherwise be the default.
 */
export function defaultCondition(
  fromStepIds: string[],
  isSelfCompleting: (stepId: string) => boolean,
): Condition | null {
  return fromStepIds.every(isSelfCompleting) ? { type: 'Always' } : null
}

/**
 * Where each transition sits — §9: "a transition's position is a *function* of its neighbours",
 * so it is computed, never stored.
 *
 * The centroid of the steps it links, which places it between them for a series and centred
 * over the fan for a branch. Unit 10 draws the spanning bar from the same neighbour geometry.
 */
export function transitionPositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Map<string, { x: number; y: number }> {
  const stepAt = new Map(
    nodes
      .filter((n) => n.kind === 'step')
      .map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]),
  )
  const positions = new Map<string, { x: number; y: number }>()

  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const neighbours = edges
      .filter((e) => e.source === tr.id || e.target === tr.id)
      .map((e) => (e.source === tr.id ? e.target : e.source))
      .map((id) => stepAt.get(id))
      .filter((p): p is { x: number; y: number } => p !== undefined)

    if (neighbours.length === 0) {
      positions.set(tr.id, { x: 0, y: 0 })
      continue
    }
    positions.set(tr.id, {
      x: neighbours.reduce((sum, p) => sum + p.x, 0) / neighbours.length,
      y: neighbours.reduce((sum, p) => sum + p.y, 0) / neighbours.length,
    })
  }
  return positions
}

/** One synchronization bar: where to draw it relative to its own node, and how far it reaches. */
export interface BarSpan {
  /** Vertical centre of the span, relative to the owning node's y. */
  offsetY: number
  /** Total height to draw, in canvas px. Never below `MIN_BAR_HEIGHT`. */
  height: number
  /** How many branches it gathers — ≥2, or there would be no bar. */
  count: number
}

export interface NodeBars {
  /** Several steps arriving — synchronization of sequences ([IEC 60848:2013] §6.2.7). */
  incoming?: BarSpan
  /** Several steps leaving — activation of parallel sequences ([IEC 60848:2013] §6.2.6). */
  outgoing?: BarSpan
}

/** So a bar is still visible when its branches happen to sit at the same height. */
export const MIN_BAR_HEIGHT = 28

/**
 * Where each **transition's** synchronization bars go — chart §6.
 *
 * `[CITED]` [IEC 60848:2013] Table 2 **[9]**, *"Synchronization preceding and/or succeeding a
 * transition"*: "When several steps are connected to the same transition, the directed links
 * from and/or to these steps are grouped, to succeed or precede the synchronization symbol
 * represented by **two parallel horizontal lines**." So the bar belongs to the **transition**, on
 * the side that has several steps — which is why this returns entries for transitions only.
 * (Verified in DIN EN 60848:2014-12, the German adoption of Ed. 3.0, and identical in Ed. 2.0.)
 *
 * **Steps never own a bar.** §6.2.3: a selection of sequences is represented "by as many
 * simultaneously enabled transitions as possible evolutions" — no symbol whatsoever. The
 * single "OR rail" this function used to emit for a branching step was **invented**; it was
 * deleted once the symbol tables were finally read (`010` §12, unit 10 rebuild).
 *
 * **The bars are drawing, not structure.** AND is link multiplicity (§4.3.2), so a bar is simply
 * how a transition with more than one step on a side is *drawn*. Nothing here changes the graph
 * — delete this function and the recipe is identical, just uglier. Which is exactly why the
 * earlier bar-*nodes* were wrong.
 *
 * Table 3 [10] makes links horizontal or vertical and [11] fixes top→bottom "by convention…
 * arrows **shall** be used if this convention is not respected". Our canvas runs left→right and
 * draws arrowheads on every edge (`RecipeBuilder.EDGE`), which is the sanctioned deviation.
 * Branches therefore fan out vertically and a bar spans their **y** range — perpendicular to the
 * link, as [9]'s "parallel lines" are to a top→bottom one. Computed from positions because React
 * Flow gives handles, not spans (§6's stated cost).
 */
export function barSpans(
  nodes: GraphNode[],
  edges: GraphEdge[],
  positions: Map<string, { x: number; y: number }>,
): Map<string, NodeBars> {
  const yOf = (id: string) => positions.get(id)?.y
  const bars = new Map<string, NodeBars>()

  const spanOf = (ownerId: string, branchIds: string[]): BarSpan | undefined => {
    if (branchIds.length < 2) return undefined
    const ys = branchIds.map(yOf).filter((y): y is number => y !== undefined)
    if (ys.length < 2) return undefined
    const [top, bottom] = [Math.min(...ys), Math.max(...ys)]
    const ownY = yOf(ownerId) ?? (top + bottom) / 2
    return {
      offsetY: (top + bottom) / 2 - ownY,
      height: Math.max(bottom - top, MIN_BAR_HEIGHT),
      count: branchIds.length,
    }
  }

  for (const node of nodes) {
    // Table 2 [9] hangs the symbol off the *transition*. A step with several succeeding
    // transitions is a selection (§6.2.3) and carries no symbol at all.
    if (node.kind !== 'transition') continue
    const incoming = spanOf(node.id, edges.filter((e) => e.target === node.id).map((e) => e.source))
    const outgoing = spanOf(node.id, edges.filter((e) => e.source === node.id).map((e) => e.target))
    if (incoming || outgoing) bars.set(node.id, { incoming, outgoing })
  }
  return bars
}

/** Rebuild the persisted steps from the canvas, keeping their positions. */
export function graphToSteps(nodes: GraphNode[]): RecipeStep[] {
  return nodes
    .filter((n) => n.kind === 'step')
    .map((n) => ({
      id: n.id,
      pea_id: n.pea_id ?? 0,
      service: n.service ?? '',
      procedure_id: n.procedure_id ?? 0,
      params: n.params ?? {},
      x: n.x ?? null,
      y: n.y ?? null,
    }))
}
