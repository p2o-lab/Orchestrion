// The event log as a standalone browser window (opened from PeaView via
// window.open on /projects/:projectId/peas/:peaId/log). It runs OUTSIDE the app
// shell (no sidebar) and opens its OWN WebSocket — the registry broadcasts to every
// listener, so this second viewer gets its own snapshot + live stream, independent
// of the main window.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PeaDetail } from '../api/types'
import { useLiveState } from '../hooks/useLiveState'
import { Icon } from '../ui/icons'
import { Spinner } from '../ui/primitives'
import { LogPanel } from '../ui/LogPanel'

export function LogWindow() {
  const { peaId } = useParams()
  const id = Number(peaId)
  const [pea, setPea] = useState<PeaDetail | null>(null)
  const [connected, setConnected] = useState(false)
  // A view-level clear: hide events before this offset. The backend log is
  // untouched (it stays in-memory / streamed-only, plan §4).
  const [cleared, setCleared] = useState(0)

  useEffect(() => {
    if (Number.isNaN(id)) return
    api.getPea(id).then(setPea).catch(() => setPea(null))
    api.liveStatus(id).then((s) => setConnected(s.connected)).catch(() => setConnected(false))
  }, [id])

  const live = useLiveState(Number.isNaN(id) ? null : id, connected)
  const liveConnected = connected && live.status === 'live'

  useEffect(() => {
    document.title = pea ? `${pea.name} — Event log` : 'Event log'
  }, [pea])

  if (!pea) {
    return (
      <div className="grid h-screen place-items-center bg-canvas">
        <Spinner className="h-6 w-6" />
      </div>
    )
  }

  const events = live.events.slice(cleared)

  return (
    <div className="flex h-screen flex-col bg-canvas text-ink">
      <header className="flex items-center justify-between border-b border-edge px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/12 text-accent">
            <Icon name="recipe" size={16} />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{pea.name} · Event log</div>
            <div className="truncate font-mono text-[11px] text-faint">{pea.endpoint_url}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ' +
              (liveConnected
                ? 'border-ok/30 bg-ok/10 text-ok'
                : 'border-edge-strong bg-white/4 text-faint')
            }
          >
            <span className={`h-1.5 w-1.5 rounded-full bg-current ${liveConnected ? 'pulse-dot' : ''}`} />
            {liveConnected ? 'live' : 'not connected'}
          </span>
          <button
            onClick={() => setCleared(live.events.length)}
            className="rounded-lg px-2.5 py-1 text-xs text-faint transition hover:bg-white/5 hover:text-dim"
          >
            Clear
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        {connected ? (
          <LogPanel events={events} />
        ) : (
          <p className="px-5 py-6 text-xs text-faint">
            This PEA isn’t connected — connect it from the main window to see live events.
          </p>
        )}
      </div>
    </div>
  )
}
