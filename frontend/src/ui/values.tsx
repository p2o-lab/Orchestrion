// Live value tiles — the read-out/write side of the 2658-4 value model (process
// values, report values, config parameters). A tile shows one value's descriptor plus
// its live reading from the WebSocket stream. Read-only values (out) render as
// gauges/pills; writable incoming values (in) become an editable control when the PEA
// is connected — a toggle for binary, an input for analog/integer.

import { useState } from 'react'
import type { LiveValue, ValueDescriptor } from '../api/types'
import { Icon } from './icons'

export type WriteFn = (name: string, value: boolean | number | string) => Promise<void>

function prettyName(name: string): string {
  // Drop a leading vendor/tag prefix segment for readability, keep the rest verbatim.
  const parts = name.split('_')
  return (parts.length > 1 ? parts.slice(1).join('_') : name).replace(/_/g, ' ')
}

function formatNumber(value: LiveValue): string {
  if (typeof value !== 'number') return String(value)
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

function DirectionChip({ desc }: { desc: ValueDescriptor }) {
  const inbound = desc.direction === 'in'
  return (
    <span
      className={
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ' +
        (inbound ? 'bg-accent/12 text-accent' : 'bg-white/6 text-faint')
      }
      title={inbound ? 'written by the POL (input)' : 'read from the PEA (output)'}
    >
      {desc.writable && <Icon name="pencil" size={9} />}
      {inbound ? 'in' : 'out'}
    </span>
  )
}

function BinaryReadout({ has, on }: { has: boolean; on: boolean }) {
  return (
    <div className="mt-3 flex items-center gap-2">
      <span className={'h-2.5 w-2.5 rounded-full ' + (!has ? 'bg-faint/40' : on ? 'bg-ok pulse-dot' : 'bg-white/25')} />
      <span className={'text-lg font-semibold ' + (!has ? 'text-faint' : on ? 'text-ok' : 'text-dim')}>
        {!has ? '—' : on ? 'ON' : 'OFF'}
      </span>
    </div>
  )
}

function BinaryToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="mt-3 flex items-center gap-2"
      title="click to set"
    >
      <span
        className={
          'relative h-5 w-9 rounded-full transition ' + (on ? 'bg-ok/80' : 'bg-white/15')
        }
      >
        <span
          className={
            'absolute top-0.5 h-4 w-4 rounded-full bg-white transition ' +
            (on ? 'left-4' : 'left-0.5')
          }
        />
      </span>
      <span className={'text-sm font-semibold ' + (on ? 'text-ok' : 'text-dim')}>
        {on ? 'ON' : 'OFF'}
      </span>
    </button>
  )
}

function NumberEditor({
  value,
  integer,
  onSet,
}: {
  value: LiveValue | undefined
  integer: boolean
  onSet: (n: number) => void
}) {
  const [draft, setDraft] = useState('')
  const has = value !== undefined
  const n = Number(draft)
  const empty = draft.trim() === ''
  // An integer-kind value (DINT) rejects a fractional entry rather than silently
  // sending a float the server would truncate.
  const bad = !empty && (Number.isNaN(n) || (integer && !Number.isInteger(n)))

  function submit() {
    if (empty || bad) return
    onSet(n)
    setDraft('')
  }

  return (
    <div className="mt-2">
      <div className="font-mono text-2xl tabular-nums text-ink">
        {has ? formatNumber(value as LiveValue) : '—'}
      </div>
      <div className="mt-2 flex gap-1.5">
        <input
          type="number"
          inputMode={integer ? 'numeric' : 'decimal'}
          step={integer ? 1 : 'any'}
          placeholder="set…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          className={
            'w-full rounded-lg border bg-elev px-2.5 py-1.5 text-sm text-ink outline-none transition focus:ring-2 ' +
            (bad
              ? 'border-danger/60 focus:border-danger focus:ring-danger/20'
              : 'border-edge-strong focus:border-accent focus:ring-accent/20')
          }
        />
        <button
          onClick={submit}
          disabled={empty || bad}
          className="rounded-lg border border-accent/45 bg-accent/12 px-3 text-xs font-semibold text-accent-bright transition hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Set
        </button>
      </div>
      {bad && <div className="mt-1 text-[11px] text-danger">{integer ? 'whole numbers only' : 'enter a number'}</div>}
    </div>
  )
}

function ValueTile({
  desc,
  value,
  onWrite,
  editable,
}: {
  desc: ValueDescriptor
  value: LiveValue | undefined
  onWrite?: WriteFn
  editable: boolean
}) {
  const has = value !== undefined
  const isBinary = desc.kind === 'binary'
  const on = isBinary && (value === true || value === 1)
  // Editable only when the PEA is connected, the value is writable, and we can write it.
  const canEdit = editable && desc.writable && !!onWrite && desc.kind !== 'string'

  return (
    <div className="group rounded-xl border border-edge bg-white/4 p-4 transition duration-150 hover:border-accent/30 hover:bg-white/6">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-xs text-dim" title={desc.name}>
          {prettyName(desc.name)}
        </span>
        <DirectionChip desc={desc} />
      </div>

      {isBinary ? (
        canEdit ? (
          <BinaryToggle on={on} onToggle={() => onWrite!(desc.name, !on)} />
        ) : (
          <BinaryReadout has={has} on={on} />
        )
      ) : canEdit ? (
        <NumberEditor
          value={value}
          integer={desc.kind === 'integer'}
          onSet={(n) => onWrite!(desc.name, n)}
        />
      ) : (
        <div className="mt-2 font-mono text-2xl tabular-nums text-ink">
          {has ? formatNumber(value as LiveValue) : <span className="text-faint">—</span>}
        </div>
      )}
    </div>
  )
}

export function ValueGrid({
  values,
  live,
  onWrite,
  editable = false,
  empty,
}: {
  values: ValueDescriptor[]
  live: Record<string, LiveValue>
  onWrite?: WriteFn
  editable?: boolean
  empty?: string
}) {
  if (values.length === 0) {
    return empty ? <p className="text-xs text-faint">{empty}</p> : null
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {values.map((v) => (
        <ValueTile key={v.name} desc={v} value={live[v.name]} onWrite={onWrite} editable={editable} />
      ))}
    </div>
  )
}
