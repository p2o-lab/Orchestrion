import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { LiveValue, LogEvent, PeaDetail, Service, ValueMeta } from '../api/types'
import { useLiveState } from '../hooks/useLiveState'
import { Button, Card, Spinner } from '../ui/primitives'
import { StatePill } from '../ui/StatePill'
import { Icon } from '../ui/icons'
import { ValueGrid } from '../ui/values'

export function PeaView() {
  const { projectId, peaId } = useParams()
  const id = Number(peaId)
  const [pea, setPea] = useState<PeaDetail | null>(null)
  // `connected` mirrors the backend's PERSISTENT connection (started/stopped only by
  // the buttons). We read the real status on open, so a connection made earlier
  // survives navigating away and back.
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  const load = useCallback(async () => setPea(await api.getPea(id)), [id])
  useEffect(() => {
    setPea(null)
    load().catch(() => setPea(null))
  }, [load])

  useEffect(() => {
    if (Number.isNaN(id)) return
    api.liveStatus(id).then((s) => setConnected(s.connected)).catch(() => setConnected(false))
  }, [id])

  const live = useLiveState(Number.isNaN(id) ? null : id, connected)
  const liveConnected = connected && live.status === 'live'

  const writeValue = useCallback(
    async (name: string, value: boolean | number | string) => {
      // Fire-and-forget: the WebSocket stream reflects the applied value back.
      await api.writeValue(id, name, value).catch(() => undefined)
    },
    [id],
  )

  useEffect(() => {
    if (live.status === 'error') setConnected(false)
  }, [live.status])

  async function toggleConnection() {
    setBusy(true)
    setConnectError(null)
    try {
      if (connected) {
        await api.disconnectPea(id)
        setConnected(false)
      } else {
        await api.connectPea(id)
        setConnected(true)
      }
    } catch (e) {
      setConnectError(e instanceof ApiError ? e.message : String(e))
      setConnected(false)
    } finally {
      setBusy(false)
    }
  }

  if (!pea) {
    return <div className="grid h-full place-items-center"><Spinner className="h-6 w-6" /></div>
  }

  const showError = connectError ?? (live.status === 'error' ? live.error : null)

  return (
    <div className="w-full px-10 py-9">
      {/* breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-faint animate-fade-in">
        <Link to="/" className="transition hover:text-dim">Workspace</Link>
        <Icon name="chevron" size={13} />
        <Link to={`/projects/${projectId}`} className="transition hover:text-dim">Project</Link>
        <Icon name="chevron" size={13} />
        <span className="text-dim">{pea.name}</span>
      </div>

      {/* header */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4 animate-fade-in">
        <div className="flex items-start gap-3.5">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent/12 text-accent">
            <Icon name="module" size={24} />
          </span>
          <div>
            <h1 className="text-2xl text-ink">{pea.name}</h1>
            <p className="mt-1 flex items-center gap-1.5 font-mono text-sm text-dim">
              <Icon name="signal" size={14} className="text-faint" /> {pea.endpoint_url}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge status={connected ? live.status : 'closed'} />
          <Button variant={connected ? 'secondary' : 'primary'} onClick={toggleConnection} disabled={busy}>
            {busy ? <Spinner className="h-4 w-4" /> : <Icon name="power" size={16} />}
            {connected ? 'Disconnect' : 'Connect'}
          </Button>
        </div>
      </div>

      {showError && (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink/90 animate-fade-in">
          <span className="mt-0.5 text-danger"><Icon name="power" size={16} /></span>
          <span>Could not reach the PEA. <span className="font-mono text-xs text-dim">— {showError}</span></span>
        </div>
      )}

      <Identification pea={pea} />

      {pea.process_values.length > 0 && (
        <>
          <div className="mb-3 mt-8 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
            <Icon name="signal" size={14} /> Process values
            <span className="font-normal normal-case tracking-normal text-faint/70">
              · cross-PEA, live regardless of service state
            </span>
          </div>
          <Card className="p-5 animate-fade-in">
            <ValueGrid
              values={pea.process_values}
              live={live.values}
              meta={live.valueMeta}
              onWrite={writeValue}
              editable={liveConnected}
            />
          </Card>
        </>
      )}

      <div className="mb-3 mt-8 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
        <Icon name="module" size={14} /> Services
      </div>
      <div className="space-y-4">
        {pea.services.map((s, i) => (
          <div key={s.name} className="animate-rise" style={{ animationDelay: `${i * 60}ms` }}>
            <ServiceCard
              peaId={id}
              service={s}
              state={live.states[s.name]}
              enabled={new Set(live.commandEn[s.name] ?? [])}
              values={live.values}
              valueMeta={live.valueMeta}
              onWrite={writeValue}
              connected={liveConnected}
            />
          </div>
        ))}
      </div>

      {connected && (
        <>
          <div className="mb-3 mt-8 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
            <Icon name="recipe" size={14} /> Event log
            <span className="font-normal normal-case tracking-normal text-faint/70">
              · state transitions, commands, operator actions
            </span>
          </div>
          <Card className="overflow-hidden p-0 animate-fade-in">
            <LogPanel events={live.events} />
          </Card>
        </>
      )}
    </div>
  )
}

// Colour per event kind ([2658-4] concepts) — literal classes so Tailwind keeps them.
const LOG_KIND: Record<string, { dot: string; label: string }> = {
  state_transition: { dot: 'bg-st-execute', label: 'state' },
  command: { dot: 'bg-accent', label: 'command' },
  connection: { dot: 'bg-ok', label: 'link' },
  value_write: { dot: 'bg-st-paused', label: 'write' },
}

function LogPanel({ events }: { events: LogEvent[] }) {
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
    <div className="max-h-80 overflow-y-auto p-2">
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

function LiveBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    connecting: { cls: 'text-warn border-warn/30 bg-warn/10', label: 'connecting' },
    live: { cls: 'text-ok border-ok/30 bg-ok/10', label: 'live' },
    error: { cls: 'text-danger border-danger/30 bg-danger/10', label: 'offline' },
    closed: { cls: 'text-faint border-edge-strong bg-white/4', label: 'disconnected' },
  }
  const m = map[status] ?? map.closed
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${m.cls}`}>
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
    <Card className="mt-6 grid grid-cols-2 gap-x-8 gap-y-4 p-5 sm:grid-cols-3 lg:grid-cols-5 animate-fade-in">
      {rows.map(([k, v]) => (
        <div key={k}>
          <div className="text-[10.5px] uppercase tracking-[0.12em] text-faint">{k}</div>
          <div className="mt-1 truncate text-sm text-ink" title={v}>{v || '—'}</div>
        </div>
      ))}
    </Card>
  )
}

// Commands offered as buttons (START is issued via "Run" with a procedure).
const BUTTON_COMMANDS = ['COMPLETE', 'STOP', 'HOLD', 'UNHOLD', 'PAUSE', 'RESUME', 'RESTART', 'RESET', 'ABORT']

function ServiceCard({
  peaId,
  service,
  state,
  enabled,
  values: live,
  valueMeta,
  onWrite,
  connected,
}: {
  peaId: number
  service: Service
  state: string | undefined
  enabled: Set<string>
  values: Record<string, LiveValue>
  valueMeta: Record<string, ValueMeta>
  onWrite: (name: string, value: boolean | number | string) => Promise<void>
  connected: boolean
}) {
  const [showNodes, setShowNodes] = useState(false)
  const [procedure, setProcedure] = useState(service.procedures[0]?.procedure_id ?? 0)
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const selectedProc = service.procedures.find((p) => p.procedure_id === procedure)
  const readouts = selectedProc
    ? [...selectedProc.report_values, ...selectedProc.process_values]
    : []

  async function run() {
    setBusy('RUN')
    setError(null)
    try {
      const nums: Record<string, number> = {}
      for (const param of selectedProc?.parameters ?? []) {
        const raw = values[param.name]
        if (raw !== undefined && raw.trim() !== '') nums[param.name] = Number(raw)
      }
      await api.startService(peaId, service.name, procedure, nums)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function command(cmd: string) {
    setBusy(cmd)
    setError(null)
    try {
      await api.sendCommand(peaId, service.name, cmd)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const canStart = connected && enabled.has('START')
  // Procedure choice is locked once running: allow it only when disconnected
  // (pre-selecting) or when Start is actually available (IDLE).
  const selectable = !connected || canStart

  return (
    <Card className="edge-top-accent overflow-hidden p-6">
      {/* hero row: name + live state */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-ink">{service.name}</h3>
        {connected ? (
          <StatePill state={state} big />
        ) : (
          <span className="rounded-full border border-edge-strong bg-white/4 px-4 py-1.5 text-sm text-faint">
            not connected
          </span>
        )}
      </div>

      {/* service-level configuration parameters (§6.2.4.3) */}
      {service.config_parameters.length > 0 && (
        <div className="mt-6">
          <div className="mb-2 text-[10.5px] uppercase tracking-[0.12em] text-faint">Configuration</div>
          {/* config params are writable via controlled assignment (§8.1.3) — not wired
              yet, so shown read-only for now (editable=false). */}
          <ValueGrid values={service.config_parameters} live={live} meta={valueMeta} />
        </div>
      )}

      {/* run: pick a procedure (click a card) + start */}
      <div className="mt-6">
        <div className="mb-2 text-[10.5px] uppercase tracking-[0.12em] text-faint">Procedure</div>
        <div className="flex flex-wrap gap-2.5">
          {service.procedures.map((p) => {
            const selected = p.procedure_id === procedure
            return (
              <button
                key={p.procedure_id}
                onClick={() => setProcedure(p.procedure_id)}
                disabled={!selectable || busy !== null}
                title={!selectable && connected ? 'Locked while running' : undefined}
                className={
                  'relative rounded-xl border px-3.5 py-2.5 text-left transition duration-150 ' +
                  (selected
                    ? 'border-accent bg-accent/12 shadow-[0_0_22px_-8px] shadow-accent'
                    : selectable
                      ? 'border-edge bg-white/4 hover:border-accent/40 hover:bg-white/6'
                      : 'border-edge bg-white/4 opacity-45 cursor-not-allowed')
                }
              >
                <div className="flex items-center gap-2 text-sm text-ink">
                  <span className="font-mono text-xs text-accent">#{p.procedure_id}</span>
                  {p.name}
                  {selected && <Icon name="chevron" size={13} className="text-accent" />}
                </div>
                <div className={`mt-1 inline-flex items-center gap-1.5 text-[11px] ${p.is_self_completing ? 'text-st-completed' : 'text-st-idle'}`}>
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  {p.is_self_completing ? 'self-completing' : 'continuous'}
                </div>
              </button>
            )
          })}
        </div>

        {/* parameter values for the selected procedure (set before Start, §4.3.1) */}
        {selectedProc && selectedProc.parameters.length > 0 && (
          <div className="mt-4 space-y-2.5">
            {selectedProc.parameters.map((param) => (
              <div key={param.name} className="flex flex-wrap items-center gap-3">
                <label className="min-w-40 text-sm text-dim" title={param.name}>
                  {param.name}
                </label>
                {param.kind === 'string' ? (
                  <span className="text-xs text-faint">string parameters not settable yet</span>
                ) : (
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="value"
                    value={values[param.name] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [param.name]: e.target.value }))}
                    disabled={!selectable || busy !== null}
                    className="w-40 rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-50"
                  />
                )}
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <Button variant="primary" onClick={run} disabled={!canStart || busy !== null}>
            {busy === 'RUN' ? <Spinner className="h-4 w-4" /> : <Icon name="power" size={16} />}
            Run
          </Button>
          {connected && !canStart && (
            <span className="text-xs text-faint">Start is available from IDLE</span>
          )}
        </div>
      </div>

      {/* live readouts for the selected procedure — report values (#6) + process
          values (#7/#8). Live during EXECUTE; report values freeze at Completed/
          Stopped/Aborted (§6.2.5). Empty for procedures that declare none. */}
      {readouts.length > 0 && (
        <div className="mt-6">
          <div className="mb-2 text-[10.5px] uppercase tracking-[0.12em] text-faint">
            Live readouts · {selectedProc?.name}
          </div>
          <ValueGrid values={readouts} live={live} meta={valueMeta} onWrite={onWrite} editable={connected} />
        </div>
      )}

      {/* command buttons (enabled strictly from live CommandEn) */}
      <div className="mt-6">
        <div className="mb-2 text-[10.5px] uppercase tracking-[0.12em] text-faint">Commands</div>
        <div className="flex flex-wrap gap-2">
          {BUTTON_COMMANDS.map((c) => {
            const on = connected && enabled.has(c)
            const danger = c === 'ABORT' || c === 'STOP'
            return (
              <button
                key={c}
                onClick={() => command(c)}
                disabled={!on || busy !== null}
                className={
                  'rounded-lg border px-3.5 py-1.5 text-xs font-semibold tracking-wide transition duration-150 ' +
                  (on
                    ? danger
                      ? 'border-danger/45 bg-danger/10 text-danger hover:bg-danger/20'
                      : 'border-accent/45 bg-accent/12 text-accent-bright hover:bg-accent/20'
                    : 'cursor-not-allowed border-edge bg-white/3 text-faint')
                }
              >
                {busy === c ? '…' : c}
              </button>
            )
          })}
        </div>
        {error && (
          <div className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2 font-mono text-xs text-ink/90">
            {error}
          </div>
        )}
      </div>

      {/* control interface (binding detail) */}
      <button
        onClick={() => setShowNodes((s) => !s)}
        className="mt-6 inline-flex items-center gap-1.5 text-xs font-medium text-dim transition hover:text-ink"
      >
        <Icon name="chevron" size={14} className={`transition ${showNodes ? 'rotate-90' : ''}`} />
        Control interface · {service.control_nodes.length} nodes
      </button>
      {showNodes && (
        <div className="mt-3 overflow-x-auto rounded-xl border border-edge animate-fade-in">
          <table className="w-full text-left text-xs">
            <thead className="bg-white/3 text-faint">
              <tr className="border-b border-edge">
                <th className="px-3.5 py-2.5 font-medium">Attribute</th>
                <th className="px-3.5 py-2.5 font-medium">Access</th>
                <th className="px-3.5 py-2.5 font-medium">Identifier</th>
              </tr>
            </thead>
            <tbody className="font-mono text-dim">
              {service.control_nodes.map((n) => (
                <tr key={n.name} className="border-b border-edge/40 transition last:border-0 hover:bg-white/3">
                  <td className="whitespace-nowrap px-3.5 py-2 text-ink">{n.name}</td>
                  <td className="whitespace-nowrap px-3.5 py-2">
                    <span className={n.access.includes('WRITE') ? 'text-st-execute' : 'text-faint'}>{n.access}</span>
                  </td>
                  <td className="max-w-xs truncate px-3.5 py-2" title={n.identifier}>{n.identifier}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
