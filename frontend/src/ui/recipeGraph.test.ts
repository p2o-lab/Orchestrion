// The chart mapping — `docs/POL_Recipe_Chart_GRAFCET.md`, rebuilt at `010` unit 9.
//
// **Rewritten, not tweaked.** The previous suite tested AND/OR *bar nodes*, which this unit
// deletes: §4.3.2 makes AND/OR **link multiplicity**, so the bars are a drawing convention and
// never were graph elements. Seven of its sixteen tests described behaviour that no longer
// exists. START/END nodes went the same way (§1, §3).

import { describe, expect, it } from 'vitest'

import type { Condition, MasterRecipe } from '../api/types'
import {
  END_ID,
  MIN_BAR_HEIGHT,
  barSpans,
  defaultCondition,
  graphToSteps,
  graphToTransitions,
  initialStepId,
  isPitTransition,
  recipeToGraph,
  transitionPositions,
  type GraphEdge,
  type GraphNode,
} from './recipeGraph'

const step = (id: string, x = 0, y = 0, pea_id = 1): GraphNode => ({
  id, kind: 'step', pea_id, service: 'Stirring', procedure_id: 2, params: {}, x, y,
})
const transition = (id: string, condition?: Condition): GraphNode => ({
  id, kind: 'transition', condition,
})
const link = (source: string, target: string): GraphEdge => ({ source, target })

const hot: Condition = {
  type: 'ValueThreshold', pea_id: 1, value_name: 'Temp', op: '>', threshold: 80,
}
const always: Condition = { type: 'Always' }

/** Sort ids so a comparison does not depend on edge order. */
const canon = (ts: ReturnType<typeof graphToTransitions>['transitions']) =>
  ts.map((t) => ({ ...t, from_ids: [...t.from_ids].sort(), to_ids: [...t.to_ids].sort() }))

describe('two node kinds, nothing else', () => {
  it('maps a series: s1 → T → s2', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), transition('t1', hot), step('s2')],
      [link('s1', 't1'), link('t1', 's2')],
    )
    expect(error).toBeNull()
    expect(transitions).toEqual([{ from_ids: ['s1'], to_ids: ['s2'], condition: hot }])
  })

  it('rejects a step wired straight to another step', () => {
    const { error } = graphToTransitions([step('s1'), step('s2')], [link('s1', 's2')])
    expect(error).toMatch(/alternates steps and transitions/i)
    expect(error).toMatch(/put a transition between them/i)
  })

  it('rejects two transitions wired together', () => {
    const { error } = graphToTransitions(
      [step('s1'), transition('t1'), transition('t2')],
      [link('s1', 't1'), link('t1', 't2')],
    )
    expect(error).toMatch(/alternates steps and transitions/i)
  })

  it('rejects a link to a node that no longer exists', () => {
    const { error } = graphToTransitions([step('s1')], [link('s1', 'ghost')])
    expect(error).toMatch(/no longer exists/i)
  })

  it('rejects a transition with nothing before it', () => {
    const { error } = graphToTransitions(
      [transition('t1'), step('s1')],
      [link('t1', 's1')],
    )
    expect(error).toMatch(/at least one step before/i)
  })
})

describe('AND and OR come from link count, not from nodes', () => {
  it('AND divergence: one transition, several succeeding steps', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), transition('t1', hot), step('s2'), step('s3')],
      [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')],
    )
    expect(error).toBeNull()
    expect(canon(transitions)).toEqual([
      { from_ids: ['s1'], to_ids: ['s2', 's3'], condition: hot },
    ])
  })

  it('AND convergence: several preceding steps, one transition', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), step('s2'), transition('t1', hot), step('s3')],
      [link('s1', 't1'), link('s2', 't1'), link('t1', 's3')],
    )
    expect(error).toBeNull()
    expect(canon(transitions)).toEqual([
      { from_ids: ['s1', 's2'], to_ids: ['s3'], condition: hot },
    ])
  })

  it('OR divergence: one step, several succeeding transitions', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), transition('t1', hot), transition('t2', always), step('s2'), step('s3')],
      [link('s1', 't1'), link('t1', 's2'), link('s1', 't2'), link('t2', 's3')],
    )
    expect(error).toBeNull()
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.from_ids[0] === 's1')).toBe(true)
  })

  it('OR convergence: several transitions into one step', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), step('s2'), transition('t1', hot), transition('t2', always), step('s3')],
      [link('s1', 't1'), link('t1', 's3'), link('s2', 't2'), link('t2', 's3')],
    )
    expect(error).toBeNull()
    expect(transitions).toHaveLength(2)
    expect(transitions.every((t) => t.to_ids[0] === 's3')).toBe(true)
  })
})

describe('the end of a branch is an unwired output (§3)', () => {
  it('a transition with no successor serialises to the END sentinel', () => {
    const { transitions, error } = graphToTransitions(
      [step('s1'), transition('t1', hot)],
      [link('s1', 't1')],
    )
    expect(error).toBeNull()
    expect(transitions).toEqual([{ from_ids: ['s1'], to_ids: [END_ID], condition: hot }])
  })

  it('isPitTransition sees the difference', () => {
    const edges = [link('s1', 't1'), link('t1', 's2'), link('s2', 't2')]
    expect(isPitTransition('t2', edges)).toBe(true)
    expect(isPitTransition('t1', edges)).toBe(false)
  })

  it('END never becomes a node when a recipe is loaded', () => {
    const recipe: MasterRecipe = {
      header: { name: 'r', version: 1, author: '', product: '' },
      formula: {},
      steps: [{ id: 's1', pea_id: 1, service: 'Stirring', procedure_id: 2, params: {} }],
      transitions: [{ from_ids: ['s1'], to_ids: [END_ID], condition: hot }],
    }
    const { nodes, edges } = recipeToGraph(recipe)
    expect(nodes.map((n) => n.kind).sort()).toEqual(['step', 'transition'])
    expect(nodes.some((n) => n.id === END_ID)).toBe(false)
    expect(edges).toEqual([link('s1', 't1')])   // the output is simply unwired
  })
})

describe('round trips', () => {
  const roundTrip = (recipe: MasterRecipe) => {
    const { nodes, edges } = recipeToGraph(recipe)
    const { transitions, error } = graphToTransitions(nodes, edges)
    expect(error).toBeNull()
    return canon(transitions)
  }

  it('a diamond survives: split, two branches, join, end', () => {
    const recipe: MasterRecipe = {
      header: { name: 'd', version: 1, author: '', product: '' },
      formula: {},
      steps: ['s0', 'sA', 'sB', 's4'].map((id) => ({
        id, pea_id: 1, service: 'Stirring', procedure_id: 2, params: {},
      })),
      transitions: [
        { from_ids: ['s0'], to_ids: ['sA', 'sB'], condition: always },
        { from_ids: ['sA', 'sB'], to_ids: ['s4'], condition: hot },
        { from_ids: ['s4'], to_ids: [END_ID], condition: always },
      ],
    }
    expect(roundTrip(recipe)).toEqual(canon(recipe.transitions))
  })

  it('an OR selection survives, including which branch each transition takes', () => {
    const recipe: MasterRecipe = {
      header: { name: 'sel', version: 1, author: '', product: '' },
      formula: {},
      steps: ['s0', 'sX', 'sY'].map((id) => ({
        id, pea_id: 1, service: 'Stirring', procedure_id: 2, params: {},
      })),
      transitions: [
        { from_ids: ['s0'], to_ids: ['sX'], condition: hot },
        { from_ids: ['s0'], to_ids: ['sY'], condition: always },
        { from_ids: ['sX'], to_ids: [END_ID], condition: always },
        { from_ids: ['sY'], to_ids: [END_ID], condition: always },
      ],
    }
    expect(roundTrip(recipe)).toEqual(canon(recipe.transitions))
  })

  it('keeps each step\'s persisted position', () => {
    const recipe: MasterRecipe = {
      header: { name: 'p', version: 1, author: '', product: '' },
      formula: {},
      steps: [{ id: 's1', pea_id: 3, service: 'Stirring', procedure_id: 1, params: { Duration: 5 }, x: 120, y: 40 }],
      transitions: [],
    }
    const { nodes } = recipeToGraph(recipe)
    expect(graphToSteps(nodes)).toEqual([
      { id: 's1', pea_id: 3, service: 'Stirring', procedure_id: 1, params: { Duration: 5 }, x: 120, y: 40 },
    ])
  })
})

describe('the initial step is inferred, and must be unique (§2 / item 1337)', () => {
  it('finds the one step no transition targets', () => {
    const nodes = [step('s1'), transition('t1'), step('s2')]
    expect(initialStepId(nodes, [link('s1', 't1'), link('t1', 's2')])).toBe('s1')
  })

  it('returns null when two steps have no predecessor', () => {
    const nodes = [step('s1'), step('s2'), transition('t1'), step('s3')]
    const edges = [link('s1', 't1'), link('s2', 't1'), link('t1', 's3')]
    expect(initialStepId(nodes, edges)).toBeNull()
  })

  it('returns null for a cycle — every step is targeted, so none is initial', () => {
    // The very shape IEC 60848 Figure 2 draws, and why the inference needs cycles rejected.
    const nodes = [step('s1'), transition('t1'), step('s2'), transition('t2')]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('s2', 't2'), link('t2', 's1')]
    expect(initialStepId(nodes, edges)).toBeNull()
  })
})

describe('the default receptivity depends on the procedure kind (§4)', () => {
  const selfCompleting = () => true
  const continuous = () => false

  it('is Always when every preceding step ends by itself', () => {
    expect(defaultCondition(['s1'], selfCompleting)).toEqual({ type: 'Always' })
  })

  it('is null for a continuous step — the author must supply a real one', () => {
    expect(defaultCondition(['s1'], continuous)).toBeNull()
  })

  it('is null if ANY preceding step is continuous, not just a lone one', () => {
    // §5(b): a continuous step may feed an AND-join, which is exactly where `=1` would
    // otherwise have been the default and would complete it the instant it started.
    expect(defaultCondition(['sA', 'sB'], (id) => id !== 'sA')).toBeNull()
  })
})

describe('synchronization bars are drawn from link count — Table 2 [9], chart §6', () => {
  const at = (entries: [string, number, number][]) =>
    new Map(entries.map(([id, x, y]) => [id, { x, y }]))

  it('gives a transition with several succeeding steps an outgoing bar (AND divergence)', () => {
    const nodes = [step('s1'), transition('t1'), step('s2'), step('s3')]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')]
    const bars = barSpans(nodes, edges, at([['s1', 0, 100], ['t1', 100, 100], ['s2', 200, 40], ['s3', 200, 160]]))
    expect(bars.get('t1')?.outgoing).toEqual({ offsetY: 0, height: 120, count: 2 })
    expect(bars.get('t1')?.incoming).toBeUndefined()   // only one step feeds it
  })

  it('gives a transition with several preceding steps an incoming bar (AND convergence)', () => {
    const nodes = [step('s1'), step('s2'), transition('t1'), step('s3')]
    const edges = [link('s1', 't1'), link('s2', 't1'), link('t1', 's3')]
    const bars = barSpans(nodes, edges, at([['s1', 0, 0], ['s2', 0, 200], ['t1', 100, 100], ['s3', 200, 100]]))
    expect(bars.get('t1')?.incoming).toEqual({ offsetY: 0, height: 200, count: 2 })
  })

  it('gives a step with several succeeding transitions NOTHING — a selection has no symbol', () => {
    // [IEC 60848:2013] §6.2.3: a selection of sequences "is represented by as many
    // simultaneously enabled transitions as possible evolutions". No bar, no rail. Unit 10
    // originally drew a single "OR rail" here; it was invented, and the standard deletes it.
    const nodes = [step('s1'), transition('t1'), transition('t2')]
    const edges = [link('s1', 't1'), link('s1', 't2')]
    const bars = barSpans(nodes, edges, at([['s1', 0, 100], ['t1', 100, 50], ['t2', 100, 150]]))
    expect(bars.get('s1')).toBeUndefined()
    expect(bars.size).toBe(0)
  })

  it('gives a step with several preceding transitions nothing either (a convergence of selections)', () => {
    // §6.2.3's mirror: several sequences rejoining is still just several transitions. Only
    // Table 2 [9] — several *steps* on one transition — draws a symbol.
    const nodes = [transition('t1'), transition('t2'), step('s1')]
    const edges = [link('t1', 's1'), link('t2', 's1')]
    expect(barSpans(nodes, edges, at([['t1', 0, 50], ['t2', 0, 150], ['s1', 100, 100]])).size).toBe(0)
  })

  it('offsets the bar when the branches are not centred on their node', () => {
    const nodes = [step('s1'), transition('t1'), step('s2'), step('s3')]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')]
    // branches at y 200 and 300 → centre 250, while the transition sits at 100
    const bars = barSpans(nodes, edges, at([['s1', 0, 100], ['t1', 100, 100], ['s2', 200, 200], ['s3', 200, 300]]))
    expect(bars.get('t1')?.outgoing).toEqual({ offsetY: 150, height: 100, count: 2 })
  })

  it('keeps a minimum height when branches sit at the same y', () => {
    const nodes = [step('s1'), transition('t1'), step('s2'), step('s3')]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')]
    const bars = barSpans(nodes, edges, at([['s1', 0, 0], ['t1', 100, 0], ['s2', 200, 0], ['s3', 200, 0]]))
    expect(bars.get('t1')?.outgoing?.height).toBe(MIN_BAR_HEIGHT)
  })

  it('draws no bar at all for a plain series — one link each side', () => {
    const nodes = [step('s1'), transition('t1'), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    expect(barSpans(nodes, edges, at([['s1', 0, 0], ['t1', 100, 0], ['s2', 200, 0]])).size).toBe(0)
  })

  it('is pure decoration — it never changes the transitions', () => {
    // The bars are how multiplicity is *drawn* (§4.3.2); deleting them would leave the recipe
    // identical. This is the invariant the bar-*node* model could not hold.
    const nodes = [step('s1'), transition('t1'), step('s2'), step('s3')]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')]
    const before = graphToTransitions(nodes, edges).transitions
    barSpans(nodes, edges, at([['s1', 0, 0], ['t1', 100, 0], ['s2', 200, 0], ['s3', 200, 90]]))
    expect(graphToTransitions(nodes, edges).transitions).toEqual(before)
  })
})

describe('transitions are placed, not stored (§9)', () => {
  it('sits at the centroid of the steps it links', () => {
    const nodes = [step('s1', 0, 0), transition('t1'), step('s2', 100, 50)]
    const at = transitionPositions(nodes, [link('s1', 't1'), link('t1', 's2')])
    expect(at.get('t1')).toEqual({ x: 50, y: 25 })
  })

  it('centres over the fan of an AND divergence', () => {
    const nodes = [step('s1', 50, 0), transition('t1'), step('s2', 0, 100), step('s3', 100, 100)]
    const at = transitionPositions(nodes, [link('s1', 't1'), link('t1', 's2'), link('t1', 's3')])
    expect(at.get('t1')).toEqual({ x: 50, y: 200 / 3 })
  })

  it('recipeToGraph gives transitions no stored coordinates', () => {
    const recipe: MasterRecipe = {
      header: { name: 'r', version: 1, author: '', product: '' },
      formula: {},
      steps: [{ id: 's1', pea_id: 1, service: 'Stirring', procedure_id: 2, params: {} }],
      transitions: [{ from_ids: ['s1'], to_ids: [END_ID], condition: always }],
    }
    const tr = recipeToGraph(recipe).nodes.find((n) => n.kind === 'transition')!
    expect(tr.x).toBeUndefined()
    expect(tr.y).toBeUndefined()
  })
})
