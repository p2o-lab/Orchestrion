// The chart mapping — `docs/POL_Recipe_Chart_GRAFCET.md`, rebuilt at `010` unit 9.
//
// **Rewritten, not tweaked.** The previous suite tested AND/OR *bar nodes*, which this unit
// deletes: §4.3.2 makes AND/OR **link multiplicity**, so the bars are a drawing convention and
// never were graph elements. Seven of its sixteen tests described behaviour that no longer
// exists. START/END nodes went the same way (§1, §3).

import { describe, expect, it } from 'vitest'

import type { Condition, MasterRecipe } from '../api/types'
import {
  BRANCH_GAP_Y,
  BRANCH_OFFSET_X,
  END_ID,
  MIN_BAR_HEIGHT,
  barSpans,
  branchActionFor,
  branchRanks,
  branchSpawnPosition,
  defaultCondition,
  reprioritise,
  selectionBranchMayDefault,
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

describe('branch authoring — chart §7', () => {
  const at = (entries: [string, number, number][]) =>
    new Map(entries.map(([id, x, y]) => [id, { x, y }]))

  describe('each action hangs off exactly one node kind', () => {
    it('a transition opens a PARALLEL branch — §6.2.6, one transition to several steps', () => {
      expect(branchActionFor('transition')).toBe('parallel')
    })

    it('a step opens a SELECTION branch — §6.2.3, one step to several transitions', () => {
      expect(branchActionFor('step')).toBe('selection')
    })

    it('nothing selected offers nothing', () => {
      expect(branchActionFor(null)).toBeNull()
      expect(branchActionFor(undefined)).toBeNull()
    })
  })

  describe('placement stacks branches downward', () => {
    it('puts a first branch to the right of its owner', () => {
      const pos = branchSpawnPosition('t1', [], at([['t1', 100, 50]]))
      expect(pos).toEqual({ x: 100 + BRANCH_OFFSET_X, y: 50 })
    })

    it('puts the next one below the lowest sibling, not on top of it', () => {
      const edges = [link('t1', 's2'), link('t1', 's3')]
      const pos = branchSpawnPosition('t1', edges, at([['t1', 100, 50], ['s2', 300, 0], ['s3', 300, 140]]))
      expect(pos).toEqual({ x: 300, y: 140 + BRANCH_GAP_Y })
    })

    it('ignores links that are not the owner’s own outgoing ones', () => {
      const edges = [link('t1', 's2'), link('tOther', 's9')]
      const pos = branchSpawnPosition('t1', edges, at([['t1', 0, 0], ['s2', 200, 0], ['s9', 200, 900]]))
      expect(pos).toEqual({ x: 200, y: 0 + BRANCH_GAP_Y })
    })

    it('falls back to the origin when the owner has no known position', () => {
      expect(branchSpawnPosition('ghost', [], at([]))).toEqual({ x: BRANCH_OFFSET_X, y: 0 })
    })

    it('ignores a sibling whose position is unknown rather than crashing', () => {
      const edges = [link('s1', 't1'), link('s1', 't2')]
      const pos = branchSpawnPosition('s1', edges, at([['s1', 0, 0], ['t1', 150, 60]]))
      expect(pos).toEqual({ x: 150, y: 60 + BRANCH_GAP_Y })
    })
  })

  describe('a new selection branch does not default to Always', () => {
    it('allows a default when the step has no outgoing transition yet', () => {
      // The first transition off a step is a plain series, not a selection — the usual
      // `defaultCondition` rules apply there (chart §4).
      expect(selectionBranchMayDefault('s1', [])).toBe(true)
    })

    it('REFUSES once the step already branches', () => {
      // §6.2.3's NOTE puts exclusivity on the designer ("muss"), and under §8's priority
      // arbitration a branch whose sibling is constantly true can never fire. Defaulting the
      // new one to `Always` would author a provably dead branch.
      expect(selectionBranchMayDefault('s1', [link('s1', 't1')])).toBe(false)
    })

    it('counts only that step’s own outgoing links', () => {
      expect(selectionBranchMayDefault('s1', [link('s2', 't1'), link('t9', 's1')])).toBe(true)
    })
  })
})

describe('OR-branch priority — chart §8', () => {
  /** s1 branches to t1 and t2; s2 is a plain series through t3. */
  const selectionGraph = (): { nodes: GraphNode[]; edges: GraphEdge[] } => ({
    nodes: [
      step('s1'), step('s2'),
      { ...transition('t1'), priority: 0 },
      { ...transition('t2'), priority: 1 },
      { ...transition('t3'), priority: 2 },
    ],
    edges: [link('s1', 't1'), link('s1', 't2'), link('s2', 't3')],
  })

  describe('only a real selection gets a rank', () => {
    it('ranks the two transitions leaving one step', () => {
      const { nodes, edges } = selectionGraph()
      const ranks = branchRanks(nodes, edges)
      expect(ranks.get('t1')).toEqual({ rank: 1, of: 2, stepId: 's1' })
      expect(ranks.get('t2')).toEqual({ rank: 2, of: 2, stepId: 's1' })
    })

    it('gives a plain series no rank — there is nothing to arbitrate', () => {
      const { nodes, edges } = selectionGraph()
      expect(branchRanks(nodes, edges).has('t3')).toBe(false)
    })

    it('restarts at ① for each step, because priority is per selection group', () => {
      const nodes: GraphNode[] = [
        step('s1'), step('s2'),
        { ...transition('a1'), priority: 0 }, { ...transition('a2'), priority: 1 },
        { ...transition('b1'), priority: 2 }, { ...transition('b2'), priority: 3 },
      ]
      const edges = [link('s1', 'a1'), link('s1', 'a2'), link('s2', 'b1'), link('s2', 'b2')]
      const ranks = branchRanks(nodes, edges)
      expect(ranks.get('a1')!.rank).toBe(1)
      expect(ranks.get('b1')!.rank).toBe(1) // not 3
    })

    it('ranks by priority, not by node-array position', () => {
      const nodes: GraphNode[] = [
        step('s1'),
        { ...transition('t1'), priority: 5 },
        { ...transition('t2'), priority: 2 },
      ]
      const edges = [link('s1', 't1'), link('s1', 't2')]
      const ranks = branchRanks(nodes, edges)
      expect(ranks.get('t2')!.rank).toBe(1)
      expect(ranks.get('t1')!.rank).toBe(2)
    })

    it('ranks a multi-from transition once, under its lowest-sorted from-step', () => {
      // An AND convergence can sit in two selection groups; the choice must be deterministic
      // or the badge flickers between renders.
      const nodes: GraphNode[] = [
        step('sA'), step('sB'),
        { ...transition('shared'), priority: 1 },
        { ...transition('otherA'), priority: 0 },
        { ...transition('otherB'), priority: 2 },
      ]
      const edges = [
        link('sA', 'shared'), link('sB', 'shared'),
        link('sA', 'otherA'), link('sB', 'otherB'),
      ]
      expect(branchRanks(nodes, edges).get('shared')).toEqual({ rank: 2, of: 2, stepId: 'sA' })
    })
  })

  describe('reprioritise swaps two keys and leaves everything else alone', () => {
    it('moves a branch up', () => {
      const { nodes, edges } = selectionGraph()
      const ranks = branchRanks(reprioritise(nodes, edges, 't2', 'up'), edges)
      expect(ranks.get('t2')!.rank).toBe(1)
      expect(ranks.get('t1')!.rank).toBe(2)
    })

    it('moves a branch down', () => {
      const { nodes, edges } = selectionGraph()
      expect(branchRanks(reprioritise(nodes, edges, 't1', 'down'), edges).get('t1')!.rank).toBe(2)
    })

    it('does not touch a transition outside the group', () => {
      const { nodes, edges } = selectionGraph()
      const next = reprioritise(nodes, edges, 't2', 'up')
      expect(next.find((n) => n.id === 't3')!.priority).toBe(2)
    })

    it('refuses to move the first branch up, or the last one down', () => {
      const { nodes, edges } = selectionGraph()
      expect(reprioritise(nodes, edges, 't1', 'up')).toBe(nodes)
      expect(reprioritise(nodes, edges, 't2', 'down')).toBe(nodes)
    })

    it('refuses to reorder something that has no rank', () => {
      const { nodes, edges } = selectionGraph()
      expect(reprioritise(nodes, edges, 't3', 'up')).toBe(nodes)
    })

    it('does not mutate the input', () => {
      const { nodes, edges } = selectionGraph()
      reprioritise(nodes, edges, 't2', 'up')
      expect(nodes.find((n) => n.id === 't2')!.priority).toBe(1)
    })
  })

  describe('priority reaches the engine as list order', () => {
    it('emits transitions in priority order, not node order', () => {
      // `engine.py` walks MasterRecipe.transitions by index and the first eligible transition
      // to claim a step wins — so emission order IS the arbitration.
      const nodes: GraphNode[] = [
        step('s1'), step('sX'), step('sY'),
        { ...transition('t1', hot), priority: 1 },
        { ...transition('t2', hot), priority: 0 },
      ]
      const edges = [link('s1', 't1'), link('t1', 'sX'), link('s1', 't2'), link('t2', 'sY')]
      const { transitions, error } = graphToTransitions(nodes, edges)
      expect(error).toBeNull()
      expect(transitions.map((t) => t.to_ids[0])).toEqual(['sY', 'sX'])
    })

    it('puts unranked transitions after ranked ones, keeping their relative order', () => {
      const nodes: GraphNode[] = [
        step('s1'), step('sX'), step('sY'), step('sZ'),
        transition('tA', hot),
        { ...transition('tRanked', hot), priority: 0 },
        transition('tB', hot),
      ]
      const edges = [
        link('s1', 'tA'), link('tA', 'sX'),
        link('s1', 'tRanked'), link('tRanked', 'sY'),
        link('s1', 'tB'), link('tB', 'sZ'),
      ]
      const { transitions } = graphToTransitions(nodes, edges)
      expect(transitions.map((t) => t.to_ids[0])).toEqual(['sY', 'sX', 'sZ'])
    })

    it('survives a round trip — a reordered chart reloads in the same order', () => {
      // The defect §8 names: priority used to be an invisible artefact of array position, so
      // a load-edit-save could silently reshuffle which branch wins.
      const recipe: MasterRecipe = {
        header: { name: 'sel', version: 1, author: '', product: '' },
        formula: {},
        steps: ['s0', 'sX', 'sY'].map((id) => ({
          id, pea_id: 1, service: 'Stirring', procedure_id: 2, params: {},
        })),
        transitions: [
          { from_ids: ['s0'], to_ids: ['sX'], condition: hot },
          { from_ids: ['s0'], to_ids: ['sY'], condition: hot },
          { from_ids: ['sX'], to_ids: [END_ID], condition: always },
          { from_ids: ['sY'], to_ids: [END_ID], condition: always },
        ],
      }
      const { nodes, edges } = recipeToGraph(recipe)
      const swapped = reprioritise(nodes, edges, 't2', 'up') // author promotes branch 2
      const { transitions } = graphToTransitions(swapped, edges)
      expect(transitions.slice(0, 2).map((t) => t.to_ids[0])).toEqual(['sY', 'sX'])

      const reloaded = recipeToGraph({ ...recipe, transitions })
      const again = graphToTransitions(reloaded.nodes, reloaded.edges).transitions
      expect(again.map((t) => t.to_ids[0])).toEqual(transitions.map((t) => t.to_ids[0]))
    })
  })
})
