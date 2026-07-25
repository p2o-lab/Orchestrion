// The scrollable, auto-scrolling event-log list (M4). Shared so the log window
// (and anywhere else) renders identical rows. Colour + label per event kind.

import { useEffect, useRef } from 'react'
import type { LogEvent } from '../api/types'

// Colour per event kind ([2658-4] concepts) — literal classes so Tailwind keeps them.
const LOG_KIND: Record<string, { dot: string; label: string }> = {
  state_transition: { dot: 'bg-st-execute', label: 'state' },
  command: { dot: 'bg-accent', label: 'command' },
  connection: { dot: 'bg-ok', label: 'link' },
  value_write: { dot: 'bg-st-paused', label: 'write' },
}

export function LogPanel({ events }: { events: LogEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  // Auto-scroll to the newest line as events arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length])

  if (events.length === 0) {
    return (
      <p className="px-5 py-6 text-xs text-faint">
        No events yet — command a service or write a value to see them here.
      </p>
    )
  }
  return (
    <div className="h-full overflow-y-auto p-2">
      {events.map((e, i) => {
        const k = LOG_KIND[e.kind] ?? { dot: 'bg-faint', label: e.kind }
        const time = new Date(e.timestamp).toLocaleTimeString([], { hour12: false })
        return (
          <div
            key={i}
            className="flex items-start gap-3 rounded-lg px-3 py-1.5 font-mono text-xs transition hover:bg-white/3"
          >
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${k.dot}`} />
            <span className="shrink-0 tabular-nums text-faint">{time}</span>
            <span className="w-16 shrink-0 uppercase tracking-wide text-faint/80">{k.label}</span>
            <span className="text-ink">
              {e.message}
              {e.detail && <span className="text-faint"> — {e.detail}</span>}
            </span>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
