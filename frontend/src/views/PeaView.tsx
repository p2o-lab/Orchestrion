import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PeaDetail, Service } from '../api/types'
import { useLiveState } from '../hooks/useLiveState'
import { Button, Card, Spinner } from '../ui/primitives'
import { StatePill } from '../ui/StatePill'

// A conventional command order for the CommandEn indicator row (2658-4 Table 14).
const COMMANDS = ['START', 'STOP', 'HOLD', 'UNHOLD', 'PAUSE', 'RESUME', 'RESET', 'RESTART', 'COMPLETE', 'ABORT']

export function PeaView() {
  const { projectId, peaId } = useParams()
  const id = Number(peaId)
  const [pea, setPea] = useState<PeaDetail | null>(null)
  const [connected, setConnected] = useState(true) // auto-connect on open

  const load = useCallback(async () => setPea(await api.getPea(id)), [id])
  useEffect(() => {
    setPea(null)
    load().catch(() => setPea(null))
  }, [load])

  const live = useLiveState(Number.isNaN(id) ? null : id, connected)

  if (!pea) {
    return <div className="grid h-full place-items-center"><Spinner className="h-6 w-6" /></div>
  }

  return (
    <div className="mx-auto max-w-6xl px-10 py-9">
      <Link to={`/projects/${projectId}`} className="text-sm text-faint transition hover:text-ink">
        ← Back
      </Link>

      {/* header */}
      <div className="mt-3 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl text-ink">{pea.name}</h1>
          <p className="mt-1 font-mono text-sm text-dim">{pea.endpoint_url}</p>
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge status={live.status} error={live.error} />
          <Button variant={connected ? 'secondary' : 'primary'} onClick={() => setConnected((c) => !c)}>
            {connected ? 'Disconnect' : 'Connect'}
          </Button>
        </div>
      </div>

      {live.status === 'error' && (
        <div className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink/90">
          Could not reach the PEA. {live.error && <span className="font-mono text-xs">— {live.error}</span>}
        </div>
      )}

      {/* identification (§12) */}
      <Identification pea={pea} />

      {/* services */}
      <h2 className="mb-3 mt-8 text-[11px] font-semibold uppercase tracking-wider text-faint">
        Services
      </h2>
      <div className="space-y-4">
        {pea.services.map((s) => (
          <ServiceCard
            key={s.name}
            service={s}
            state={live.states[s.name]}
            enabled={new Set(live.commandEn[s.name] ?? [])}
            connected={connected && live.status === 'live'}
          />
        ))}
      </div>
    </div>
  )
}

function LiveBadge({ status, error }: { status: string; error: string | null }) {
  const map: Record<string, { cls: string; label: string }> = {
    connecting: { cls: 'text-warn', label: 'connecting' },
    live: { cls: 'text-ok', label: 'live' },
    error: { cls: 'text-danger', label: 'offline' },
    closed: { cls: 'text-faint', label: 'disconnected' },
  }
  const m = map[status] ?? map.closed
  return (
    <span className={`inline-flex items-center gap-2 text-xs font-medium ${m.cls}`} title={error ?? ''}>
      {status === 'connecting' ? (
        <Spinner className="h-3 w-3" />
      ) : (
        <span className={`h-2 w-2 rounded-full bg-current ${status === 'live' ? 'pulse-dot' : ''}`} />
      )}
      {m.label}
    </span>
  )
}

function Identification({ pea }: { pea: PeaDetail }) {
  const rows: [string, string][] = [
    ['Type', pea.type_name],
    ['MTP version', pea.mtp_version],
    ['Device revision', pea.device_revision],
    ['Manufacturer', pea.manufacturer_uri],
    ['Product code', pea.product_code],
  ]
  return (
    <Card className="mt-6 p-5">
      <div className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
        {rows.map(([k, v]) => (
          <div key={k}>
            <div className="text-[11px] uppercase tracking-wider text-faint">{k}</div>
            <div className="mt-0.5 truncate text-sm text-ink" title={v}>{v || '—'}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function ServiceCard({
  service,
  state,
  enabled,
  connected,
}: {
  service: Service
  state: string | undefined
  enabled: Set<string>
  connected: boolean
}) {
  const [showNodes, setShowNodes] = useState(false)
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg text-ink">{service.name}</h3>
        {connected ? <StatePill state={state} big /> : <span className="text-sm text-faint">— not connected —</span>}
      </div>

      {/* procedures */}
      <div className="mt-5">
        <div className="mb-2 text-[11px] uppercase tracking-wider text-faint">Procedures</div>
        <div className="flex flex-wrap gap-2">
          {service.procedures.map((p) => (
            <div key={p.procedure_id} className="rounded-lg border border-edge bg-white/3 px-3 py-2">
              <div className="text-sm text-ink">
                <span className="mr-2 font-mono text-xs text-accent">#{p.procedure_id}</span>
                {p.name}
              </div>
              <div className="mt-0.5 text-[11px] text-faint">
                {p.is_self_completing ? 'self-completing' : 'continuous'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* CommandEn indicators (live; M3 will make these actionable) */}
      <div className="mt-5">
        <div className="mb-2 text-[11px] uppercase tracking-wider text-faint">
          Commands {connected && <span className="text-faint/70">· enabled shown lit (CommandEn)</span>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {COMMANDS.map((c) => {
            const on = connected && enabled.has(c)
            return (
              <span
                key={c}
                className={
                  'rounded-md border px-2.5 py-1 text-[11px] font-medium tracking-wide transition ' +
                  (on
                    ? 'border-accent/50 bg-accent/15 text-accent-bright'
                    : 'border-edge bg-white/3 text-faint')
                }
              >
                {c}
              </span>
            )
          })}
        </div>
      </div>

      {/* control interface (binding detail) */}
      <button
        onClick={() => setShowNodes((s) => !s)}
        className="mt-5 text-xs font-medium text-dim transition hover:text-ink"
      >
        {showNodes ? '▾' : '▸'} Control interface · {service.control_nodes.length} nodes
      </button>
      {showNodes && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-edge">
          <table className="w-full text-left text-xs">
            <thead className="text-faint">
              <tr className="border-b border-edge">
                <th className="px-3 py-2 font-medium">Attribute</th>
                <th className="px-3 py-2 font-medium">Access</th>
                <th className="px-3 py-2 font-medium">Identifier</th>
              </tr>
            </thead>
            <tbody className="font-mono text-dim">
              {service.control_nodes.map((n) => (
                <tr key={n.name} className="border-b border-edge/50 last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5 text-ink">{n.name}</td>
                  <td className="whitespace-nowrap px-3 py-1.5">{n.access}</td>
                  <td className="max-w-xs truncate px-3 py-1.5" title={n.identifier}>{n.identifier}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
