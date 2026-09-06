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
//     you *draw* that; drawing conventions are the canvas's job, not the model's.
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
  /** Persisted canvas position — UI-only and non-normative, on **both** kinds.
   *
   *  §9 originally gave a transition none, because its place is a *function* of its
   *  neighbours (§6 needs it to span its branches) and so could be recomputed on every
   *  load. That is still the **fallback** — and it is what a chart saved before this, or
   *  never dragged, gets. But recomputing *unconditionally* silently threw away a layout
   *  the author had arranged by hand, and rearranged the chart behind their back on the
   *  next visit. §9 called adding these "purely additive"; this is that addition. */
  x?: number | null
  y?: number | null
  /** transition only — the receptivity */
  condition?: Condition
  /** transition only — **OR-branch priority**, chart §8. Not a wire field: `Transition` has
   *  none, because priority *is* the position in `MasterRecipe.transitions` and the engine
   *  reads it as such (`engine.py` — `ready` is walked in list-index order, first claim on a
   *  step wins). This is the canvas's sort key for producing that list, derived from the index
   *  on load and honoured by `graphToTransitions` on save. Absent = "after everything ranked". */
  priority?: number
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
 * step) lives in `validateChart`, and is enforced server-side regardless: a recipe can be POSTed straight
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

  // **Emission order is the priority** (chart §8): the engine walks `MasterRecipe.transitions`
  // by index and the first eligible one to claim a step wins. Before the priority badge this was
  // whatever order the node array happened to hold — an invisible artefact. Now it is the
  // explicit `priority` key, stable-sorted so unranked transitions keep their relative order
  // and land after the ranked ones.
  const ordered = nodes
    .filter((n) => n.kind === 'transition')
    .map((n, i) => ({ n, i }))
    .sort((a, b) => (a.n.priority ?? Infinity) - (b.n.priority ?? Infinity) || a.i - b.i)
    .map(({ n }) => n)

  const transitions: Transition[] = []
  for (const tr of ordered) {
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
      // Carried so a hand-placed transition comes back where it was left. `null` rather
      // than omitted when unknown, matching how steps serialise.
      x: tr.x ?? null,
      y: tr.y ?? null,
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
    // The index *is* the priority (chart §8) — carry it explicitly so the canvas can show and
    // change it, and so a re-save reproduces the order instead of reshuffling it.
    nodes.push({ id, kind: 'transition', condition: t.condition, priority: i, x: t.x, y: t.y })
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
 * The inference is only sound because **cycles are rejected** (§2/§10). IEC 60848's own
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
 * over the fan for a branch. The spanning bar is drawn from the same neighbour geometry.
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
 * deleted once the symbol tables were finally read.
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

// ── branch authoring — chart §7 ───────────────────────────────────────────────────────────

/**
 * The two ways to open a branch. Each hangs off exactly one node kind, and that is not a UI
 * preference — it follows from what the two structures *are*:
 *
 *   • `parallel`  — one transition, several succeeding **steps**. [IEC 60848:2013] §6.2.6
 *     "Activation of parallel sequences": the synchronization symbol "is used in this structure
 *     to indicate the simultaneous activity of several sequences". Only a **transition** can
 *     open one, because only a transition may precede several steps (Table 2 [9]).
 *   • `selection` — one step, several succeeding **transitions**. §6.2.3: a selection "is
 *     represented by as many simultaneously enabled transitions as possible evolutions". Only a
 *     **step** can open one.
 *
 * Both preserve §4.4's alternation by construction — a transition spawns a step, a step spawns
 * a transition — so the palette cannot be used to build an illegal chart.
 */
export type BranchAction = 'parallel' | 'selection'

/** Which branch action the selected node admits, or `null` when nothing usable is selected. */
export function branchActionFor(kind: NodeKind | null | undefined): BranchAction | null {
  if (kind === 'transition') return 'parallel'
  if (kind === 'step') return 'selection'
  return null
}

/** How far a new branch is placed from its siblings. Flow runs left→right, so branches stack
 *  in **y** and a new one lands below the lowest existing sibling. */
export const BRANCH_GAP_Y = 110
/** How far right of its owner a *first* branch is placed, when there are no siblings yet. */
export const BRANCH_OFFSET_X = 190

/**
 * Where to drop the node a branch action creates.
 *
 * Below the lowest sibling already leaving `ownerId` — so repeated clicks stack downward
 * instead of piling up — and to the right of the owner when there is no sibling yet. Pure, so
 * the placement is testable without a canvas; React Flow supplies the live positions, exactly
 * as it does for `barSpans`.
 */
export function branchSpawnPosition(
  ownerId: string,
  edges: GraphEdge[],
  positions: Map<string, { x: number; y: number }>,
): { x: number; y: number } {
  const owner = positions.get(ownerId) ?? { x: 0, y: 0 }
  const siblings = edges
    .filter((e) => e.source === ownerId)
    .map((e) => positions.get(e.target))
    .filter((p): p is { x: number; y: number } => p !== undefined)

  if (siblings.length === 0) return { x: owner.x + BRANCH_OFFSET_X, y: owner.y }
  return {
    x: Math.max(...siblings.map((p) => p.x)),
    y: Math.max(...siblings.map((p) => p.y)) + BRANCH_GAP_Y,
  }
}

/**
 * May a **new** selection branch off this step default to `Always`?
 *
 * No, once the step already has an outgoing transition. §6.2.3's NOTE makes exclusivity the
 * designer's duty — [DIN EN 60848:2014-12] "Der Entwickler **muss** sicherstellen, dass die
 * Transitionsbedingungen … untereinander exklusiv sind" — and under the priority arbitration of
 * chart §8 a branch whose sibling is constantly true **can never fire**. Defaulting it to
 * `Always` would author a provably dead branch, so it is left blank and flagged instead.
 *
 * This is narrower than §8's deferred exclusivity *lint*: no overlap is detected here, we
 * simply decline to write a receptivity we know is wrong.
 */
export function selectionBranchMayDefault(stepId: string, edges: GraphEdge[]): boolean {
  return edges.filter((e) => e.source === stepId).length === 0
}

// ── OR-branch priority — chart §8 ─────────────────────────────────────────────────────────
//
// Priority only *means* anything between transitions competing for the same step: the engine
// walks the list in order and the first eligible transition to claim a step wins, so two
// transitions that share no from-step never race. The badge therefore ranks a transition
// **within its selection group**, not globally — ①②③ off one step, starting again at ① off
// the next.
//
// GRAFCET itself expresses priority *inside the receptivities* — §6.2.3 EXAMPLE 2, `a` versus
// `ā·b`. We cannot write that (`Not` is missing from the condition union — see
// `ui/conditions.ts`), so we hoist the same intent into the chart as an explicit rank. That is
// SFC arbitration ([IEC 61131-3]) rather than GRAFCET conformance, and §8 says so.

export interface BranchRank {
  /** 1-based position among the transitions leaving this step. */
  rank: number
  /** How many transitions leave it — always ≥2, or there is no selection to rank. */
  of: number
  /** The step whose selection group this rank belongs to. */
  stepId: string
}

/** Transitions leaving `stepId`, in priority order. */
function outgoingInPriorityOrder(stepId: string, nodes: GraphNode[], edges: GraphEdge[]): GraphNode[] {
  const ids = new Set(edges.filter((e) => e.source === stepId).map((e) => e.target))
  return nodes
    .filter((n) => n.kind === 'transition' && ids.has(n.id))
    .map((n, i) => ({ n, i }))
    .sort((a, b) => (a.n.priority ?? Infinity) - (b.n.priority ?? Infinity) || a.i - b.i)
    .map(({ n }) => n)
}

/**
 * The ①②③ each branching transition wears. Only transitions in a **selection** — one of
 * several leaving a common step (§6.2.3) — get one; a plain series has nothing to arbitrate.
 *
 * A transition with several from-steps (an AND convergence) could sit in more than one
 * selection group. It is ranked in the group of its **lowest-sorted** from-step, deterministic
 * so the badge never flickers, and the case is vanishingly rare in practice — an author who
 * builds it can still see the other group's ordering from the sibling badges.
 */
export function branchRanks(nodes: GraphNode[], edges: GraphEdge[]): Map<string, BranchRank> {
  const ranks = new Map<string, BranchRank>()
  const steps = nodes.filter((n) => n.kind === 'step').map((n) => n.id).sort()

  for (const stepId of steps) {
    const group = outgoingInPriorityOrder(stepId, nodes, edges)
    if (group.length < 2) continue
    group.forEach((tr, i) => {
      if (ranks.has(tr.id)) return // already ranked by a lower-sorted from-step
      ranks.set(tr.id, { rank: i + 1, of: group.length, stepId })
    })
  }
  return ranks
}

/**
 * Move a transition one place up or down within its selection group.
 *
 * Implemented as a **swap of the two `priority` keys**, not a renumbering: only the relative
 * order inside the group matters to the engine, so swapping leaves every other transition's
 * position — and therefore every other group's arbitration — untouched.
 *
 * Returns `nodes` unchanged when the move is not possible (no rank, already at the end), so
 * the caller can wire it to a button without guarding first.
 */
export function reprioritise(
  nodes: GraphNode[],
  edges: GraphEdge[],
  transitionId: string,
  direction: 'up' | 'down',
): GraphNode[] {
  const rank = branchRanks(nodes, edges).get(transitionId)
  if (rank === undefined) return nodes

  const group = outgoingInPriorityOrder(rank.stepId, nodes, edges)
  const index = group.findIndex((n) => n.id === transitionId)
  const target = direction === 'up' ? index - 1 : index + 1
  if (target < 0 || target >= group.length) return nodes

  // Both may be unranked (`priority` absent) on a chart built this session; fall back to the
  // group position so a swap still produces a definite, distinct order.
  const a = group[index]
  const b = group[target]
  const pa = a.priority ?? index
  const pb = b.priority ?? target
  if (pa === pb) return nodes

  return nodes.map((n) =>
    n.id === a.id ? { ...n, priority: pb } : n.id === b.id ? { ...n, priority: pa } : n,
  )
}

// ── starvable joins — an authoring WARNING, never a rejection ─────────────────────────────

/** One step whose AND-join can be starved by a sibling branch. */
export interface StarvableJoin {
  /** The step that feeds both the join and at least one other transition. */
  stepId: string
  /** The join — a transition gathering several steps (§6.2.7). */
  joinId: string
  /** The sibling transitions that can consume `stepId` first and strand the join. */
  escapeIds: string[]
}

/**
 * Charts that can strand a run — chart §8/§10, `010` deadlock discussion (2026-08-08).
 *
 * **The shape:** a step feeds an AND-join *and* has another outgoing transition. If the sibling
 * fires first it consumes the step, `RESET`s it and marks it `DONE`; since cycles are rejected
 * that step can never be active again, so the join is **permanently dead** and whatever waits on
 * it waits for ever. Nothing malfunctions — the sibling winning is correct SFC arbitration
 * (§8, `engine.py`) — the *combination* is what strands the run. The engine's `held_by_armed` closes
 * this only once the join is armed; the window before that is real.
 *
 * **This is a warning and must stay one.** The shape is a legitimate idiom — "wait for both A and
 * B, unless the alarm fires first" — so rejecting it would trade a real capability for a
 * guarantee this check cannot actually give. It also only catches the shapes we thought to
 * enumerate, which is the guessing Rule 1 exists to stop.
 *
 * **This is the cheap stand-in, not the fix.** The real answer is a **runtime liveness check**
 * in the engine: after a pass where nothing fired, compute which transitions are still reachable
 * and fail the run with a named diagnosis when none is. That is *decidable* — it fires exactly
 * when the run is provably dead, needs no threshold, and catches stranded runs from chart forms
 * nobody enumerated here. Deliberately deferred to its own backend increment.
 */
export function starvableJoins(nodes: GraphNode[], edges: GraphEdge[]): StarvableJoin[] {
  const fromCount = new Map<string, number>()
  for (const e of edges) fromCount.set(e.target, (fromCount.get(e.target) ?? 0) + 1)

  const found: StarvableJoin[] = []
  for (const step of nodes.filter((n) => n.kind === 'step')) {
    const outgoing = edges.filter((e) => e.source === step.id).map((e) => e.target)
    if (outgoing.length < 2) continue // no sibling can steal the step
    for (const joinId of outgoing) {
      // A join gathers several steps; only then can losing this one strand it.
      if ((fromCount.get(joinId) ?? 0) < 2) continue
      found.push({ stepId: step.id, joinId, escapeIds: outgoing.filter((id) => id !== joinId) })
    }
  }
  return found
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
