import { describe, expect, it } from 'vitest'
import type { Condition } from '../api/types'
import type { GraphEdge, GraphNode } from './recipeGraph'
import { validateChart } from './validateChart'

const step = (id: string): GraphNode => ({
  id, kind: 'step', pea_id: 1, service: 'Stirring', procedure_id: 2, params: {}, x: 0, y: 0,
})
const transition = (id: string, condition?: Condition): GraphNode => ({ id, kind: 'transition', condition })
const link = (source: string, target: string): GraphEdge => ({ source, target })

const always: Condition = { type: 'Always' }
const hot: Condition = { type: 'ValueThreshold', pea_id: 1, value_name: 'Temp', op: '>', threshold: 80 }

/** Everything self-completing unless named. */
const selfCompleting = (continuous: string[] = []) => (id: string) => !continuous.includes(id)

const rules = (problems: { rule: string }[]) => problems.map((p) => p.rule).sort()

/** s1 → t1 → s2, the smallest valid chart. */
const series = () => ({
  nodes: [step('s1'), transition('t1', hot), step('s2')],
  edges: [link('s1', 't1'), link('t1', 's2')],
})

describe('a well-formed chart has nothing to say', () => {
  it('passes a plain series', () => {
    const { nodes, edges } = series()
    expect(validateChart(nodes, edges, selfCompleting())).toEqual([])
  })

  it('says nothing about an empty chart — not started is not wrong', () => {
    expect(validateChart([], [], selfCompleting())).toEqual([])
  })

  it('passes a diamond: split, two branches, join', () => {
    const nodes = [
      step('s0'), step('sA'), step('sB'), step('s4'),
      transition('tSplit', hot), transition('tJoin', hot),
    ]
    const edges = [
      link('s0', 'tSplit'), link('tSplit', 'sA'), link('tSplit', 'sB'),
      link('sA', 'tJoin'), link('sB', 'tJoin'), link('tJoin', 's4'),
    ]
    expect(validateChart(nodes, edges, selfCompleting())).toEqual([])
  })
})

describe('exactly one initial step — [IEC 61512-1] item 1337', () => {
  it('flags two beginnings and names them', () => {
    const nodes = [step('s1'), step('sOrphan'), transition('t1', hot), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    const found = validateChart(nodes, edges, selfCompleting())
    expect(rules(found)).toEqual(['initial-step'])
    expect(found[0].severity).toBe('error')
    expect(found[0].nodeIds).toEqual(['s1', 'sOrphan'])
    expect(found[0].message).toMatch(/exactly one beginning/i)
  })

  it('flags none at all, and says a loop may be why', () => {
    // Every step is a transition target.
    const nodes = [step('s1'), step('s2'), transition('t1', hot), transition('t2', hot)]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('s2', 't2'), link('t2', 's1')]
    const found = validateChart(nodes, edges, selfCompleting())
    expect(found.some((p) => p.rule === 'initial-step')).toBe(true)
    expect(found.find((p) => p.rule === 'initial-step')!.message).toMatch(/loop/i)
  })
})

describe('no cycles — chart §2/§10', () => {
  it('flags a loop and names the steps in it', () => {
    const nodes = [step('s1'), step('s2'), transition('t1', hot), transition('t2', hot)]
    const edges = [link('s1', 't1'), link('t1', 's2'), link('s2', 't2'), link('t2', 's1')]
    const found = validateChart(nodes, edges, selfCompleting())
    const cycle = found.find((p) => p.rule === 'cycle')!
    expect(cycle.severity).toBe('error')
    expect(cycle.nodeIds).toEqual(['s1', 's2'])
  })

  it('does not mistake an AND-divergence rejoining for a cycle', () => {
    // Two parallel branches converging is a DAG, not a loop.
    const nodes = [
      step('s0'), step('sA'), step('sB'), step('s4'),
      transition('tSplit', hot), transition('tJoin', hot),
    ]
    const edges = [
      link('s0', 'tSplit'), link('tSplit', 'sA'), link('tSplit', 'sB'),
      link('sA', 'tJoin'), link('sB', 'tJoin'), link('tJoin', 's4'),
    ]
    expect(validateChart(nodes, edges, selfCompleting()).some((p) => p.rule === 'cycle')).toBe(false)
  })

  it('catches a self-loop', () => {
    const nodes = [step('s1'), transition('t1', hot)]
    const edges = [link('s1', 't1'), link('t1', 's1')]
    expect(validateChart(nodes, edges, selfCompleting()).some((p) => p.rule === 'cycle')).toBe(true)
  })
})

describe('Always on a continuous step — step model §2', () => {
  it('flags a bare Always after a continuous step', () => {
    const nodes = [step('s1'), transition('t1', always), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    const found = validateChart(nodes, edges, selfCompleting(['s1']))
    const problem = found.find((p) => p.rule === 'always-on-continuous')!
    expect(problem.severity).toBe('error')
    expect(problem.nodeIds).toEqual(['t1', 's1'])
    expect(problem.message).toMatch(/instant it starts/i)
  })

  it('allows Always after a self-completing step — completion is the other gate', () => {
    const nodes = [step('s1'), transition('t1', always), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    expect(validateChart(nodes, edges, selfCompleting()).some((p) => p.rule === 'always-on-continuous')).toBe(false)
  })

  it('catches an Always NESTED in an Or — stricter than the server, deliberately', () => {
    // `Or` is true the moment any child is, so a buried Always is exactly as fatal. The server's
    // `isinstance(cond, Always)` misses this; the gap is recorded in `010`.
    const nested: Condition = { type: 'Or', conditions: [hot, always] }
    const nodes = [step('s1'), transition('t1', nested), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    expect(validateChart(nodes, edges, selfCompleting(['s1'])).some((p) => p.rule === 'always-on-continuous')).toBe(true)
  })

  it('checks every preceding step of a join, not just the first', () => {
    // chart §5(b): a continuous step may also feed an AND-join.
    const nodes = [step('s1'), step('s2'), transition('tJoin', always), step('s3')]
    const edges = [link('s1', 'tJoin'), link('s2', 'tJoin'), link('tJoin', 's3')]
    const found = validateChart(nodes, edges, selfCompleting(['s2']))
    expect(found.find((p) => p.rule === 'always-on-continuous')!.nodeIds).toEqual(['tJoin', 's2'])
  })
})

describe('severity and ordering', () => {
  it('reports a starvable join as a WARNING, not an error', () => {
    const nodes = [
      step('s1'), step('s2'), step('s4'), step('s5'),
      transition('tJoin', hot), transition('tEsc', hot),
    ]
    const edges = [
      link('s1', 'tJoin'), link('s2', 'tJoin'), link('tJoin', 's4'),
      link('s1', 'tEsc'), link('tEsc', 's5'),
    ]
    const found = validateChart(nodes, edges, selfCompleting())
    // s2 also has no predecessor here, so an initial-step error is expected alongside.
    const join = found.find((p) => p.rule === 'starvable-join')!
    expect(join.severity).toBe('warning')
  })

  it('puts errors before warnings', () => {
    const nodes = [
      step('s1'), step('s2'), step('s4'), step('s5'),
      transition('tJoin', hot), transition('tEsc', hot),
    ]
    const edges = [
      link('s1', 'tJoin'), link('s2', 'tJoin'), link('tJoin', 's4'),
      link('s1', 'tEsc'), link('tEsc', 's5'),
    ]
    const found = validateChart(nodes, edges, selfCompleting())
    const firstWarning = found.findIndex((p) => p.severity === 'warning')
    const lastError = found.map((p) => p.severity).lastIndexOf('error')
    expect(lastError).toBeLessThan(firstWarning)
  })

  it('reports several independent problems at once', () => {
    const nodes = [step('s1'), step('sOrphan'), transition('t1', always), step('s2')]
    const edges = [link('s1', 't1'), link('t1', 's2')]
    expect(rules(validateChart(nodes, edges, selfCompleting(['s1'])))).toEqual([
      'always-on-continuous',
      'initial-step',
    ])
  })
})
