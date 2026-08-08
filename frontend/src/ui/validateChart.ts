// Chart validation for the builder — `010` unit 12, `docs/POL_Recipe_Chart_GRAFCET.md` §10.
//
// **This is an authoring aid, not a safety boundary.** The server enforces all of this on save
// (`api/recipes.py:_validate_against_project`, HTTP 422) and a recipe can be `POST`ed straight
// past this builder, so nothing here is load-bearing for correctness — it exists so an author
// sees the problem while drawing instead of at the end.
//
// For the same reason these findings **do not block Save**. If this module and the server ever
// drift, a blocking builder would stop work the server would have accepted; a warning one just
// shows a stale message. Only the server says no.

import type { Condition } from '../api/types'
import { containsAlways } from './conditions'
import { starvableJoins, type GraphEdge, type GraphNode } from './recipeGraph'

export type Severity = 'error' | 'warning'

export interface ChartProblem {
  severity: Severity
  /** Stable slug, so the UI can group without parsing prose. */
  rule: 'initial-step' | 'cycle' | 'always-on-continuous' | 'starvable-join'
  message: string
  /** The nodes at fault, for highlighting. */
  nodeIds: string[]
}

/**
 * The initial step — [IEC 61512-1] item 1337, *"a defined beginning and end"*, **singular**.
 * Mirrors `_check_exactly_one_initial_step`.
 */
function checkInitialStep(nodes: GraphNode[], edges: GraphEdge[]): ChartProblem[] {
  const steps = nodes.filter((n) => n.kind === 'step')
  if (steps.length === 0) return [] // an empty chart is "not started", not "wrong"
  const targeted = new Set(edges.filter((e) => nodes.find((n) => n.id === e.source)?.kind === 'transition').map((e) => e.target))
  const initial = steps.filter((s) => !targeted.has(s.id)).map((s) => s.id).sort()

  if (initial.length === 1) return []
  return [
    {
      severity: 'error',
      rule: 'initial-step',
      message:
        initial.length === 0
          ? 'No initial step: every step is a transition target (a loop?). A recipe needs exactly one place to begin.'
          : `${initial.length} steps have nothing before them (${initial.join(', ')}). A recipe needs exactly one beginning.`,
      nodeIds: initial,
    },
  ]
}

/**
 * No loops — chart §2/§10. Mirrors `_check_no_cycles`, Kahn's algorithm, and names the steps
 * that survive so the message is actionable.
 *
 * ISA-88 describes steps *"in series, in parallel, or a combination of both"* (item 1339) with a
 * defined beginning and end, and never a loop. GRAFCET does permit cycles (§6.2.2), but per
 * chart §0a GRAFCET is a borrowed notation and ISA-88 is the conformance target.
 */
function checkNoCycles(nodes: GraphNode[], edges: GraphEdge[]): ChartProblem[] {
  const stepIds = nodes.filter((n) => n.kind === 'step').map((n) => n.id)
  const successors = new Map<string, Set<string>>(stepIds.map((id) => [id, new Set<string>()]))
  const incoming = new Map<string, number>(stepIds.map((id) => [id, 0]))

  // step → transition → step, collapsed to step → step.
  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const froms = edges.filter((e) => e.target === tr.id).map((e) => e.source)
    const tos = edges.filter((e) => e.source === tr.id).map((e) => e.target)
    for (const from of froms) {
      const out = successors.get(from)
      if (!out) continue
      for (const to of tos) {
        if (!successors.has(to) || out.has(to)) continue // not a step, or already counted
        out.add(to)
        incoming.set(to, (incoming.get(to) ?? 0) + 1)
      }
    }
  }

  const queue = stepIds.filter((id) => incoming.get(id) === 0)
  let settled = 0
  while (queue.length > 0) {
    const id = queue.pop()!
    settled += 1
    for (const to of successors.get(id) ?? []) {
      const left = (incoming.get(to) ?? 0) - 1
      incoming.set(to, left)
      if (left === 0) queue.push(to)
    }
  }

  if (settled === stepIds.length) return []
  const looped = stepIds.filter((id) => (incoming.get(id) ?? 0) > 0).sort()
  return [
    {
      severity: 'error',
      rule: 'cycle',
      message:
        `The chart loops back on itself (${looped.join(', ')}). ISA-88 procedures run from a ` +
        'defined beginning to a defined end (item 1337); repeating steps is not modelled.',
      nodeIds: looped,
    },
  ]
}

/**
 * `Always` is invalid on a transition with a **continuous** step before it — for a continuous
 * procedure the receptivity *is* the completion criterion (step model §2), so it would complete
 * the service the instant it started. Stated over the whole `from_ids`, because a continuous
 * step may also feed an AND-join (chart §4, §5(b)).
 *
 * ⚠ **Deliberately stricter than the server.** `_check_continuous_steps_have_a_real_receptivity`
 * tests `isinstance(cond, Always)` — a *bare* `Always` only. An `Always` nested inside an `Or` is
 * exactly as fatal (an `Or` is true the moment any child is) and the server currently accepts it.
 * This uses `containsAlways`, which walks the tree. **The server gap is the real defect and is
 * recorded in `010`;** until it is closed, a chart can be flagged here and still save.
 */
function checkAlwaysOnContinuous(
  nodes: GraphNode[],
  edges: GraphEdge[],
  isSelfCompleting: (stepId: string) => boolean,
): ChartProblem[] {
  const problems: ChartProblem[] = []
  for (const tr of nodes.filter((n) => n.kind === 'transition')) {
    const condition: Condition | undefined = tr.condition
    if (!condition || !containsAlways(condition)) continue
    const continuous = edges
      .filter((e) => e.target === tr.id)
      .map((e) => e.source)
      .filter((id) => nodes.find((n) => n.id === id)?.kind === 'step' && !isSelfCompleting(id))
    if (continuous.length === 0) continue
    problems.push({
      severity: 'error',
      rule: 'always-on-continuous',
      message:
        `${continuous.join(', ')} run${continuous.length === 1 ? 's' : ''} a continuous procedure, ` +
        'whose receptivity IS its completion criterion — an always-true condition would complete ' +
        'it the instant it starts. Give the transition a real condition (a duration, a threshold, ' +
        'an operator confirmation).',
      nodeIds: [tr.id, ...continuous],
    })
  }
  return problems
}

/** Starvable joins — a **warning**, never an error. See `starvableJoins` for why. */
function checkStarvableJoins(nodes: GraphNode[], edges: GraphEdge[]): ChartProblem[] {
  return starvableJoins(nodes, edges).map((j) => ({
    severity: 'warning' as const,
    rule: 'starvable-join' as const,
    message:
      `${j.stepId} feeds the join ${j.joinId} and also ${j.escapeIds.join(', ')}. If an escape ` +
      `fires first, ${j.stepId} is consumed and the join can never fire — anything waiting on it ` +
      'waits for ever.',
    nodeIds: [j.stepId, j.joinId, ...j.escapeIds],
  }))
}

/** Every problem in the chart, errors first. */
export function validateChart(
  nodes: GraphNode[],
  edges: GraphEdge[],
  isSelfCompleting: (stepId: string) => boolean,
): ChartProblem[] {
  return [
    ...checkInitialStep(nodes, edges),
    ...checkNoCycles(nodes, edges),
    ...checkAlwaysOnContinuous(nodes, edges, isSelfCompleting),
    ...checkStarvableJoins(nodes, edges),
  ]
}
