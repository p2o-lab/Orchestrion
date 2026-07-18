// Live value tiles — the read-out side of the 2658-4 value model (process values,
// report values, config parameters). A tile shows one value's descriptor plus its
// live reading from the WebSocket stream; direction (in/out) and writability are
// surfaced, read-only values as gauges/pills, writable ones marked for editing.

import type { LiveValue, ValueDescriptor } from '../api/types'
import { Icon } from './icons'

function prettyName(name: string): string {
  // Drop a leading vendor/tag prefix segment for readability, keep the rest verbatim.
  const parts = name.split('_')
  return (parts.length > 1 ? parts.slice(1).join('_') : name).replace(/_/g, ' ')
}

function formatNumber(value: LiveValue): string {
  if (typeof value !== 'number') return String(value)
  // Integers show whole; analogs to 2 dp — enough to read a live sweep without jitter.
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

function ValueTile({ desc, value }: { desc: ValueDescriptor; value: LiveValue | undefined }) {
  const has = value !== undefined
  const isBinary = desc.kind === 'binary'
  const on = isBinary && (value === true || value === 1)

  return (
    <div className="group rounded-xl border border-edge bg-white/4 p-4 transition duration-150 hover:border-accent/30 hover:bg-white/6">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-xs text-dim" title={desc.name}>
          {prettyName(desc.name)}
        </span>
        <DirectionChip desc={desc} />
      </div>

      {isBinary ? (
        <div className="mt-3 flex items-center gap-2">
          <span
            className={
              'h-2.5 w-2.5 rounded-full ' +
              (!has ? 'bg-faint/40' : on ? 'bg-ok pulse-dot' : 'bg-white/25')
            }
          />
          <span className={'text-lg font-semibold ' + (!has ? 'text-faint' : on ? 'text-ok' : 'text-dim')}>
            {!has ? '—' : on ? 'ON' : 'OFF'}
          </span>
        </div>
      ) : (
        <div className="mt-2 flex items-baseline gap-1">
          <span className={'font-mono text-2xl tabular-nums ' + (has ? 'text-ink' : 'text-faint')}>
            {has ? formatNumber(value as LiveValue) : '—'}
          </span>
        </div>
      )}
    </div>
  )
}

export function ValueGrid({
  values,
  live,
  empty,
}: {
  values: ValueDescriptor[]
  live: Record<string, LiveValue>
  empty?: string
}) {
  if (values.length === 0) {
    return empty ? <p className="text-xs text-faint">{empty}</p> : null
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {values.map((v) => (
        <ValueTile key={v.name} desc={v} value={live[v.name]} />
      ))}
    </div>
  )
}
