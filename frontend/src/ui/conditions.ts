// Receptivity trees — pure, framework-free, tested. The editor component is a thin shell
// over this module (the `recipeGraph.ts` pattern).
//
// Authority: `docs/POL_Recipe_Chart_GRAFCET.md` §4. [IEC 60848:2013] §4.3.3 — "associated with
// each transition, the transition-condition is **a logical expression which is true or false**
// … composed of input variables and/or internal variables". *Logical expression*: `And`/`Or`
// are not an extra we bolted on, they are what the clause describes. The wire union has
// carried them since M5.0; only the editor could not author them.
//
// **`Not` is missing from the union**, so a negated receptivity cannot be expressed at all
// (chart §12 item 3). That is not cosmetic: chart §8's own cited example — [IEC 60848:2013]
// §6.2.3 EXAMPLE 2, which achieves branch priority with `a` on one branch and `ā·b` on the
// other — **cannot be written in this editor.** Adding `Not` is a wire-format change and is
// deliberately out of this editor's scope; it is recorded, not silently worked around.

import type { Condition } from '../api/types'

export type CondKind = Condition['type']

/** Every kind the union admits, in the order the editor offers them. Exhaustive by
 *  construction — `KINDS` is typed as `CondKind[]`, so a new union member fails to typecheck
 *  here until it is listed (the no-default-arm discipline of `state/classification.py`). */
export const KINDS: readonly CondKind[] = [
  'Always',
  'StateReached',
  'ValueThreshold',
  'Elapsed',
  'And',
  'Or',
] as const

export const KIND_LABELS: Record<CondKind, string> = {
  Always: 'always true (=1)',
  StateReached: 'a service reaches a state',
  ValueThreshold: 'a value crosses a threshold',
  Elapsed: 'a time has elapsed',
  And: 'ALL of…',
  Or: 'ANY of…',
}

/** A fresh condition of `kind`, ready to be filled in. Compounds start with **one** child:
 *  the backend puts `min_length=1` on both (`recipe/model.py`, audit defect P2c — an empty
 *  `Or` is permanently false and hangs the run, an empty `And` is a silent `Always`), so an
 *  empty compound must never be constructible in the first place. */
export function emptyOf(kind: CondKind, peaId?: number): Condition {
  switch (kind) {
    case 'Always':
      return { type: 'Always' }
    case 'StateReached':
      return { type: 'StateReached', pea_id: peaId ?? -1, service: '', state: 'COMPLETED' }
    case 'ValueThreshold':
      return { type: 'ValueThreshold', pea_id: peaId ?? -1, value_name: '', op: '>', threshold: 0 }
    case 'Elapsed':
      return { type: 'Elapsed', seconds: 5 }
    case 'And':
      return { type: 'And', conditions: [{ type: 'StateReached', pea_id: peaId ?? -1, service: '', state: 'COMPLETED' }] }
    case 'Or':
      return { type: 'Or', conditions: [{ type: 'StateReached', pea_id: peaId ?? -1, service: '', state: 'COMPLETED' }] }
  }
}

/** Is this tree fully filled in — i.e. safe to save? A half-authored leaf (no service picked)
 *  would serialise to something the backend rejects, so Save stays disabled until every leaf
 *  is complete, at any depth. */
export function isComplete(c: Condition): boolean {
  switch (c.type) {
    case 'Always':
      return true
    case 'StateReached':
      return c.pea_id >= 0 && c.service !== '' && c.state !== ''
    case 'ValueThreshold':
      return c.pea_id >= 0 && c.value_name !== '' && Number.isFinite(c.threshold)
    case 'Elapsed':
      return Number.isFinite(c.seconds) && c.seconds >= 0
    case 'And':
    case 'Or':
      return c.conditions.length >= 1 && c.conditions.every(isComplete)
  }
}

/** Does this tree contain an `Always` anywhere? A **continuous** procedure's receptivity *is*
 *  its completion criterion (chart §4/§5), so `Always` would complete the service the instant
 *  it started — and `Always` nested inside an `Or` is exactly as fatal as a bare one, since
 *  `Or` is true the moment any child is. `And` is included too: it is not fatal there, but a
 *  constant-true conjunct is dead weight the author almost certainly did not mean. */
export function containsAlways(c: Condition): boolean {
  if (c.type === 'Always') return true
  if (c.type === 'And' || c.type === 'Or') return c.conditions.some(containsAlways)
  return false
}

/** A compact human summary — the label beside a transition's tick on the canvas.
 *
 *  How a receptivity is *drawn* is explicitly outside IEC 60848: Ed. 3.0 adds Table 2 [7]
 *  NOTE 4, "Die Symbolik von Transitionen ist nicht Gegenstand dieser Norm … Transitionen
 *  können textuell, mit booleschen Ausdrücken, Logikplänen usw. beschrieben werden." So this
 *  is ours to choose, and text is one of the named options. `=1` for always-true is the
 *  conventional GRAFCET rendering. */
export function summarize(c: Condition): string {
  switch (c.type) {
    case 'Always':
      return '=1'
    case 'StateReached':
      return `✓ ${c.state}`
    case 'ValueThreshold':
      return `${c.value_name} ${c.op} ${c.threshold}`
    case 'Elapsed':
      return `after ${c.seconds}s`
    case 'And':
    case 'Or': {
      const joiner = c.type === 'And' ? ' AND ' : ' OR '
      // Parenthesise a nested compound so `a AND (b OR c)` never reads as `a AND b OR c`.
      const parts = c.conditions.map((k) =>
        k.type === 'And' || k.type === 'Or' ? `(${summarize(k)})` : summarize(k),
      )
      return parts.join(joiner)
    }
  }
}

// ── immutable tree editing, addressed by index path ──────────────────────────────────────
//
// A path is the list of child indices to walk from the root: `[]` is the root itself, `[2]`
// its third child, `[2, 0]` that child's first. The editor holds one tree in state and edits
// it by path, which keeps the component free of per-field `useState` — the old editor had
// eight of them, and that is precisely how a compound got flattened on the way in.

export type Path = readonly number[]

/** The subtree at `path`, or `undefined` if the path does not exist. */
export function at(root: Condition, path: Path): Condition | undefined {
  let node: Condition | undefined = root
  for (const i of path) {
    if (node === undefined || (node.type !== 'And' && node.type !== 'Or')) return undefined
    node = node.conditions[i]
  }
  return node
}

/** A copy of `root` with the subtree at `path` replaced. An unreachable path is returned
 *  unchanged rather than throwing — the caller is a UI event, not a proof. */
export function replaceAt(root: Condition, path: Path, next: Condition): Condition {
  if (path.length === 0) return next
  if (root.type !== 'And' && root.type !== 'Or') return root
  const [head, ...rest] = path
  const child = root.conditions[head]
  if (child === undefined) return root
  const conditions = [...root.conditions]
  conditions[head] = replaceAt(child, rest, next)
  return { ...root, conditions }
}

/** A copy of `root` with the child at `path` removed.
 *
 *  **The last child of a compound is never removed** — `min_length=1` again. The UI hides the
 *  remove button in that case; this is the second line of defence, because a pure function
 *  that can produce an invalid tree is a defect waiting for a caller. */
export function removeAt(root: Condition, path: Path): Condition {
  if (path.length === 0) return root // the root itself is not removable
  const parentPath = path.slice(0, -1)
  const index = path[path.length - 1]
  const parent = at(root, parentPath)
  if (parent === undefined || (parent.type !== 'And' && parent.type !== 'Or')) return root
  if (parent.conditions.length <= 1) return root
  if (index < 0 || index >= parent.conditions.length) return root
  const conditions = parent.conditions.filter((_, i) => i !== index)
  return replaceAt(root, parentPath, { ...parent, conditions })
}

/** A copy of `root` with `child` appended to the compound at `path`. */
export function appendAt(root: Condition, path: Path, child: Condition): Condition {
  const parent = at(root, path)
  if (parent === undefined || (parent.type !== 'And' && parent.type !== 'Or')) return root
  return replaceAt(root, path, { ...parent, conditions: [...parent.conditions, child] })
}

/**
 * Change the *kind* of the subtree at `path`, keeping what can be kept.
 *
 * The rule that matters: **going from a leaf into a compound wraps the leaf as its first
 * child** rather than discarding it, and **collapsing a compound to a leaf keeps its first
 * child if that child is already the target kind.** Authored work is never thrown away
 * silently — the whole reason this module exists.
 */
export function changeKind(root: Condition, path: Path, kind: CondKind, peaId?: number): Condition {
  const current = at(root, path)
  if (current === undefined || current.type === kind) return root

  const isCompound = (t: CondKind) => t === 'And' || t === 'Or'

  // leaf → compound: keep the leaf as the first child.
  if (isCompound(kind) && !isCompound(current.type))
    return replaceAt(root, path, { type: kind, conditions: [current] } as Condition)

  // compound → compound: same children, different operator.
  if (isCompound(kind) && isCompound(current.type))
    return replaceAt(root, path, { type: kind, conditions: (current as { conditions: Condition[] }).conditions } as Condition)

  // compound → leaf: if the first child is already that kind, promote it; else start fresh.
  if (!isCompound(kind) && isCompound(current.type)) {
    const first = (current as { conditions: Condition[] }).conditions[0]
    return replaceAt(root, path, first?.type === kind ? first : emptyOf(kind, peaId))
  }

  // leaf → leaf: nothing transfers between differently-shaped leaves.
  return replaceAt(root, path, emptyOf(kind, peaId))
}
