import { useState } from 'react'
import type { Condition, PeaDetail } from '../api/types'
import { Button, Modal } from '../ui/primitives'
import {
  KINDS,
  KIND_LABELS,
  appendAt,
  at,
  changeKind,
  containsAlways,
  emptyOf,
  isComplete,
  removeAt,
  replaceAt,
  summarize,
  type CondKind,
  type Path,
} from '../ui/conditions'

// The receptivity editor — `docs/POL_Recipe_Chart_GRAFCET.md` §4.
//
// **Rewritten at `010` unit 11a.** The previous version knew three leaf kinds and held eight
// `useState` fields. An incoming `And`, `Or` or `Always` fell through to `StateReached` on open
// and Save then wrote that back — **silently destroying an authored compound** (chart §11
// item 4). It now edits one `Condition` tree, so every member of the union round-trips and
// [IEC 60848:2013] §4.3.3's "logical expression" is actually authorable.
//
// All tree logic lives in `ui/conditions.ts`, pure and tested; this file is the form.

// The 7 stable [2658-4 Table 14] states worth waiting on (transient "-ing" states are fleeting).
const STABLE_STATES = ['IDLE', 'EXECUTE', 'COMPLETED', 'PAUSED', 'HELD', 'STOPPED', 'ABORTED']
const OPS = ['<', '<=', '>', '>=', '==', '!='] as const

const sel =
  'w-full rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

// Every value TagName a PEA publishes (mirrors the backend's _value_names).
function valueNames(pea: PeaDetail): string[] {
  const names = new Set<string>()
  pea.process_values.forEach((v) => names.add(v.name))
  pea.services.forEach((s) => {
    s.config_parameters.forEach((v) => names.add(v.name))
    s.procedures.forEach((p) => {
      p.report_values.forEach((v) => names.add(v.name))
      p.process_values.forEach((v) => names.add(v.name))
    })
  })
  return [...names]
}

/** The fields of a single leaf. Compounds have none — they are just a list of children. */
function LeafFields({
  c,
  peas,
  onChange,
}: {
  c: Condition
  peas: PeaDetail[]
  onChange: (next: Condition) => void
}) {
  if (c.type === 'Always')
    return (
      <p className="text-xs text-dim">
        The receptivity is constantly true (<span className="font-mono text-ink">=1</span>). For a
        self-completing procedure that is the normal case — completion is the other gate, so there
        is nothing left for you to add.
      </p>
    )

  if (c.type === 'StateReached')
    return (
      <div className="grid gap-2 sm:grid-cols-3">
        <select
          aria-label="PEA"
          className={sel}
          value={c.pea_id >= 0 ? c.pea_id : ''}
          onChange={(e) => onChange({ ...c, pea_id: Number(e.target.value), service: '' })}
        >
          <option value="" disabled>PEA…</option>
          {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select
          aria-label="Service"
          className={sel}
          value={c.service}
          disabled={c.pea_id < 0}
          onChange={(e) => onChange({ ...c, service: e.target.value })}
        >
          <option value="" disabled>Service…</option>
          {(peas.find((p) => p.id === c.pea_id)?.services ?? []).map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </select>
        <select
          aria-label="State"
          className={sel}
          value={c.state}
          onChange={(e) => onChange({ ...c, state: e.target.value })}
        >
          {STABLE_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
    )

  if (c.type === 'ValueThreshold')
    return (
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_5rem_1fr]">
        <select
          aria-label="PEA"
          className={sel}
          value={c.pea_id >= 0 ? c.pea_id : ''}
          onChange={(e) => onChange({ ...c, pea_id: Number(e.target.value), value_name: '' })}
        >
          <option value="" disabled>PEA…</option>
          {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select
          aria-label="Value"
          className={sel}
          value={c.value_name}
          disabled={c.pea_id < 0}
          onChange={(e) => onChange({ ...c, value_name: e.target.value })}
        >
          <option value="" disabled>Value…</option>
          {(() => {
            const pea = peas.find((p) => p.id === c.pea_id)
            return pea ? valueNames(pea).map((v) => <option key={v} value={v}>{v}</option>) : null
          })()}
        </select>
        <select
          aria-label="Operator"
          className={sel}
          value={c.op}
          onChange={(e) => onChange({ ...c, op: e.target.value as (typeof OPS)[number] })}
        >
          {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <input
          aria-label="Threshold"
          className={sel}
          type="number"
          value={c.threshold}
          onChange={(e) => onChange({ ...c, threshold: Number(e.target.value) })}
        />
      </div>
    )

  if (c.type === 'Elapsed')
    return (
      <div className="flex items-center gap-2">
        <input
          aria-label="Seconds"
          className={`${sel} w-32`}
          type="number"
          min={0}
          value={c.seconds}
          onChange={(e) => onChange({ ...c, seconds: Number(e.target.value) })}
        />
        <span className="text-sm text-dim">seconds after the step starts</span>
      </div>
    )

  return null // And / Or carry no fields of their own
}

/** One node of the tree, recursing into its children. */
function ConditionRow({
  root,
  path,
  peas,
  kinds,
  setRoot,
}: {
  root: Condition
  path: Path
  peas: PeaDetail[]
  kinds: readonly CondKind[]
  setRoot: (next: Condition) => void
}) {
  const node = at(root, path)
  if (node === undefined) return null
  const compound = node.type === 'And' || node.type === 'Or'
  const firstPea = peas[0]?.id

  // A `<select>` whose value has no matching `<option>` silently displays the first one
  // instead — so a withheld kind (`Always` on a continuous step) would make the control lie
  // about the tree it is editing. The current kind is therefore always offered, even when it
  // is not offer*able*; Save still refuses it, with a reason.
  const offered = kinds.includes(node.type) ? kinds : [node.type, ...kinds]

  return (
    <div className="grid gap-2">
      <select
        aria-label="Condition kind"
        className={sel}
        value={node.type}
        onChange={(e) => setRoot(changeKind(root, path, e.target.value as CondKind, firstPea))}
      >
        {offered.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
      </select>

      {!compound && (
        <LeafFields c={node} peas={peas} onChange={(next) => setRoot(replaceAt(root, path, next))} />
      )}

      {compound && (
        <div className="grid gap-2 border-l-2 border-edge-strong pl-3">
          {node.conditions.map((_, i) => (
            <div key={i} className="grid gap-2 rounded-lg border border-edge bg-panel/30 p-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-faint">
                  {node.type === 'And' ? 'and' : 'or'} · {i + 1}
                </span>
                {/* min_length=1 — the last child is not removable (audit P2c). */}
                {node.conditions.length > 1 && (
                  <button
                    type="button"
                    aria-label={`Remove condition ${i + 1}`}
                    className="rounded px-1.5 text-xs text-faint transition hover:bg-danger/10 hover:text-danger"
                    onClick={() => setRoot(removeAt(root, [...path, i]))}
                  >
                    remove
                  </button>
                )}
              </div>
              <ConditionRow root={root} path={[...path, i]} peas={peas} kinds={kinds} setRoot={setRoot} />
            </div>
          ))}
          <Button
            variant="ghost"
            small
            onClick={() => setRoot(appendAt(root, path, emptyOf('StateReached', firstPea)))}
          >
            + add condition
          </Button>
        </div>
      )}
    </div>
  )
}

export function ConditionEditor({
  peas,
  initial,
  onSave,
  onClose,
  allowAlways = true,
}: {
  peas: PeaDetail[]
  initial: Condition
  onSave: (c: Condition) => void
  onClose: () => void
  /** False when any preceding step runs a **continuous** procedure: there the receptivity *is*
   *  the completion criterion, so a constantly-true one would complete the service the instant
   *  it started (chart §4/§5, and the backend 422s it). */
  allowAlways?: boolean
}) {
  const [tree, setTree] = useState<Condition>(initial)

  // Hide `Always` where it is invalid — but only from the *offer*. A tree that already
  // contains one is still shown and still editable; refusing to render it would repeat
  // exactly the disappearing-data bug this rewrite exists to fix.
  const kinds = allowAlways ? KINDS : KINDS.filter((k) => k !== 'Always')
  const alwaysProblem = !allowAlways && containsAlways(tree)
  const complete = isComplete(tree)

  return (
    <Modal title="Edit transition condition" onClose={onClose}>
      <label className="mb-1.5 block text-xs font-medium text-dim">Advance when…</label>
      <ConditionRow root={tree} path={[]} peas={peas} kinds={kinds} setRoot={setTree} />

      <div className="mt-4 rounded-lg border border-edge bg-panel/30 px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-faint">Reads as</span>
        <p className="mt-0.5 break-words font-mono text-xs text-ink">{summarize(tree)}</p>
      </div>

      {alwaysProblem && (
        <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          A preceding step runs a <strong>continuous</strong> procedure, where the receptivity is
          the completion criterion. An always-true condition would complete it the instant it
          started — the server rejects this.
        </p>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!complete || alwaysProblem}
          onClick={() => complete && !alwaysProblem && onSave(tree)}
        >
          Save
        </Button>
      </div>
    </Modal>
  )
}
