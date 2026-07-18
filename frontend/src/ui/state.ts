// Map a [2658-4 Table 14] service-state name to its pill styling.
// Full literal class strings so Tailwind's scanner keeps them (dynamic
// `text-st-${x}` would be purged).

const STABLE: Record<string, string> = {
  IDLE: 'text-st-idle bg-st-idle/10 border-st-idle/30',
  EXECUTE: 'text-st-execute bg-st-execute/10 border-st-execute/30',
  PAUSED: 'text-st-paused bg-st-paused/10 border-st-paused/30',
  HELD: 'text-st-held bg-st-held/10 border-st-held/30',
  COMPLETED: 'text-st-completed bg-st-completed/10 border-st-completed/30',
  STOPPED: 'text-st-stopped bg-st-stopped/10 border-st-stopped/30',
  ABORTED: 'text-st-aborted bg-st-aborted/10 border-st-aborted/30',
}

const TRANSIENT = 'text-st-transient bg-st-transient/10 border-st-transient/30'

// The "-ing" states (§6.2.2.1). Execute-as-transient (self-completing) is handled
// by the PEA; here we only style what StateCur reports.
const TRANSIENT_STATES = new Set([
  'STARTING', 'STOPPING', 'ABORTING', 'HOLDING',
  'UNHOLDING', 'PAUSING', 'RESUMING', 'RESETTING', 'COMPLETING',
])

export interface StateStyle {
  cls: string
  transient: boolean
}

export function stateStyle(name: string | undefined): StateStyle {
  if (!name) return { cls: 'text-faint bg-white/5 border-edge-strong', transient: false }
  if (TRANSIENT_STATES.has(name)) return { cls: TRANSIENT, transient: true }
  return { cls: STABLE[name] ?? 'text-dim bg-white/5 border-edge-strong', transient: false }
}

// Just the fill colour for a small status dot (literal classes for Tailwind's scanner).
const DOT: Record<string, string> = {
  IDLE: 'bg-st-idle', EXECUTE: 'bg-st-execute', PAUSED: 'bg-st-paused',
  HELD: 'bg-st-held', COMPLETED: 'bg-st-completed', STOPPED: 'bg-st-stopped',
  ABORTED: 'bg-st-aborted',
}

export function stateDot(connected: boolean, state: string | undefined): string {
  if (!connected) return 'bg-st-stopped'
  if (!state) return 'bg-accent'
  if (TRANSIENT_STATES.has(state)) return 'bg-st-transient'
  return DOT[state] ?? 'bg-st-idle'
}
