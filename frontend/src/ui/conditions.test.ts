import { describe, expect, it } from 'vitest'
import type { Condition } from '../api/types'
import {
  KINDS,
  appendAt,
  at,
  changeKind,
  containsAlways,
  emptyOf,
  isComplete,
  removeAt,
  replaceAt,
  summarize,
} from './conditions'

const sr = (service: string, state = 'COMPLETED'): Condition => ({
  type: 'StateReached',
  pea_id: 1,
  service,
  state,
})
const vt = (name: string, threshold = 80): Condition => ({
  type: 'ValueThreshold',
  pea_id: 1,
  value_name: name,
  op: '>',
  threshold,
})

describe('the kind list is closed and matches the wire union', () => {
  it('offers all six members of Condition', () => {
    // If `api/types.Condition` gains a member, `KINDS` fails to typecheck until it is listed —
    // this test pins the count so a *removal* is caught too.
    expect([...KINDS].sort()).toEqual(['Always', 'And', 'Elapsed', 'Or', 'StateReached', 'ValueThreshold'])
  })

  it('can build an empty instance of every one of them', () => {
    for (const kind of KINDS) expect(emptyOf(kind, 1).type).toBe(kind)
  })

  it('starts a compound with one child, never zero', () => {
    // The backend puts `min_length=1` on And/Or (audit P2c): an empty `Or` is permanently
    // false and hangs the run; an empty `And` is a silent `Always`.
    for (const kind of ['And', 'Or'] as const) {
      const c = emptyOf(kind) as { conditions: Condition[] }
      expect(c.conditions).toHaveLength(1)
    }
  })
})

describe('completeness gates Save', () => {
  it('accepts a filled leaf and rejects a half-authored one', () => {
    expect(isComplete(sr('Stirring'))).toBe(true)
    expect(isComplete(emptyOf('StateReached'))).toBe(false) // no PEA, no service
  })

  it('is always true for Always, and true for a zero-second Elapsed', () => {
    expect(isComplete({ type: 'Always' })).toBe(true)
    expect(isComplete({ type: 'Elapsed', seconds: 0 })).toBe(true)
  })

  it('rejects a negative Elapsed', () => {
    expect(isComplete({ type: 'Elapsed', seconds: -1 })).toBe(false)
  })

  it('recurses — one bad leaf anywhere makes the whole tree incomplete', () => {
    const good: Condition = { type: 'And', conditions: [sr('Stirring'), vt('Temp')] }
    expect(isComplete(good)).toBe(true)
    const bad: Condition = { type: 'And', conditions: [sr('Stirring'), emptyOf('ValueThreshold')] }
    expect(isComplete(bad)).toBe(false)
  })

  it('rejects an empty compound even if one is somehow constructed', () => {
    expect(isComplete({ type: 'Or', conditions: [] })).toBe(false)
  })

  it('sees a bad leaf nested two levels down', () => {
    const nested: Condition = {
      type: 'And',
      conditions: [sr('Stirring'), { type: 'Or', conditions: [vt('Temp'), emptyOf('StateReached')] }],
    }
    expect(isComplete(nested)).toBe(false)
  })
})

describe('containsAlways finds a constant-true receptivity at any depth', () => {
  it('is false for a tree of real leaves', () => {
    expect(containsAlways({ type: 'And', conditions: [sr('Stirring'), vt('Temp')] })).toBe(false)
  })

  it('finds Always nested inside an Or — which is exactly as fatal as a bare one', () => {
    // A continuous step's receptivity IS its completion criterion (chart §4/§5). `Or` is true
    // the moment any child is, so a buried `Always` completes the service instantly.
    expect(containsAlways({ type: 'Or', conditions: [vt('Temp'), { type: 'Always' }] })).toBe(true)
  })

  it('finds it two levels down', () => {
    const deep: Condition = {
      type: 'And',
      conditions: [sr('Stirring'), { type: 'Or', conditions: [{ type: 'Always' }] }],
    }
    expect(containsAlways(deep)).toBe(true)
  })
})

describe('summarize renders the whole tree, not a placeholder', () => {
  it('renders each leaf', () => {
    expect(summarize({ type: 'Always' })).toBe('=1')
    expect(summarize(sr('Stirring', 'HELD'))).toBe('✓ HELD')
    expect(summarize(vt('Temp'))).toBe('Temp > 80')
    expect(summarize({ type: 'Elapsed', seconds: 30 })).toBe('after 30s')
  })

  it('joins a compound instead of saying "ALL of…"', () => {
    // The old builder printed a constant string for And/Or, so two different compounds were
    // indistinguishable on the canvas.
    expect(summarize({ type: 'And', conditions: [vt('Temp'), sr('Stirring')] })).toBe('Temp > 80 AND ✓ COMPLETED')
    expect(summarize({ type: 'Or', conditions: [vt('Temp'), sr('Stirring')] })).toBe('Temp > 80 OR ✓ COMPLETED')
  })

  it('parenthesises a nested compound so precedence cannot be misread', () => {
    const tree: Condition = {
      type: 'And',
      conditions: [sr('Stirring'), { type: 'Or', conditions: [vt('Temp'), { type: 'Elapsed', seconds: 5 }] }],
    }
    expect(summarize(tree)).toBe('✓ COMPLETED AND (Temp > 80 OR after 5s)')
  })
})

describe('tree editing by path is immutable', () => {
  const tree: Condition = {
    type: 'And',
    conditions: [sr('Stirring'), { type: 'Or', conditions: [vt('Temp'), { type: 'Elapsed', seconds: 5 }] }],
  }

  it('reads the root, a child and a grandchild', () => {
    expect(at(tree, [])).toBe(tree)
    expect(at(tree, [0])).toEqual(sr('Stirring'))
    expect(at(tree, [1, 1])).toEqual({ type: 'Elapsed', seconds: 5 })
  })

  it('returns undefined for a path that does not exist', () => {
    expect(at(tree, [9])).toBeUndefined()
    expect(at(tree, [0, 0])).toBeUndefined() // a leaf has no children
  })

  it('replaces a grandchild without mutating the original', () => {
    const next = replaceAt(tree, [1, 1], { type: 'Elapsed', seconds: 99 })
    expect(at(next, [1, 1])).toEqual({ type: 'Elapsed', seconds: 99 })
    expect(at(tree, [1, 1])).toEqual({ type: 'Elapsed', seconds: 5 }) // untouched
  })

  it('appends to a nested compound', () => {
    const next = appendAt(tree, [1], sr('Dosing'))
    expect((at(next, [1]) as { conditions: Condition[] }).conditions).toHaveLength(3)
    expect((at(tree, [1]) as { conditions: Condition[] }).conditions).toHaveLength(2)
  })

  it('removes a child', () => {
    const next = removeAt(tree, [1, 0])
    expect((at(next, [1]) as { conditions: Condition[] }).conditions).toEqual([{ type: 'Elapsed', seconds: 5 }])
  })

  it('REFUSES to remove the last child of a compound — min_length=1', () => {
    const one: Condition = { type: 'Or', conditions: [vt('Temp')] }
    expect(removeAt(one, [0])).toBe(one)
  })

  it('refuses to remove the root', () => {
    expect(removeAt(tree, [])).toBe(tree)
  })
})

describe('changeKind never silently discards authored work', () => {
  it('wraps a leaf as the first child when it becomes a compound', () => {
    // This is the whole point: the old editor threw the leaf away.
    const next = changeKind(sr('Stirring'), [], 'And')
    expect(next).toEqual({ type: 'And', conditions: [sr('Stirring')] })
  })

  it('keeps the children when swapping AND for OR', () => {
    const tree: Condition = { type: 'And', conditions: [sr('Stirring'), vt('Temp')] }
    expect(changeKind(tree, [], 'Or')).toEqual({ type: 'Or', conditions: [sr('Stirring'), vt('Temp')] })
  })

  it('promotes the first child when a compound collapses to that same leaf kind', () => {
    const tree: Condition = { type: 'And', conditions: [sr('Stirring'), vt('Temp')] }
    expect(changeKind(tree, [], 'StateReached')).toEqual(sr('Stirring'))
  })

  it('starts fresh when a compound collapses to a kind its first child is not', () => {
    const tree: Condition = { type: 'And', conditions: [sr('Stirring')] }
    expect(changeKind(tree, [], 'Elapsed')).toEqual({ type: 'Elapsed', seconds: 5 })
  })

  it('is a no-op when the kind is unchanged', () => {
    const tree: Condition = { type: 'And', conditions: [sr('Stirring')] }
    expect(changeKind(tree, [], 'And')).toBe(tree)
  })

  it('changes a nested child in place', () => {
    const tree: Condition = { type: 'And', conditions: [sr('Stirring'), vt('Temp')] }
    const next = changeKind(tree, [1], 'Or')
    expect(at(next, [1])).toEqual({ type: 'Or', conditions: [vt('Temp')] })
    expect(at(next, [0])).toEqual(sr('Stirring')) // sibling untouched
  })
})
