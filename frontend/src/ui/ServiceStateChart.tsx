// The service lifecycle chart — the [2658-4:2022] state machine (Table 14 states,
// §4.3/Figure 4 transitions) as a symmetric hub diagram. EXECUTE sits at the centre and
// the stable states radiate on straight spokes; each edge is clipped to the node borders
// and carries an arrowhead (no lines running into the boxes). Every command rides its edge
// as an inline chip that is *always drawn* as part of the diagram — dim when the command
// is not currently legal, lit and clickable when CommandEn allows it, so an operator can
// drive a transition straight from the wire. The live state glows; the edge it is
// transiting flows and shows its transient "-ing" name; Reset appears only from a terminal.

import {
  NODE_H,
  NODE_W,
  STATE_EDGES,
  STATE_NODES,
  VIEW_H,
  VIEW_W,
  type ChartEdge,
} from './serviceStateMachine'

const NODES = new Map(STATE_NODES.map((n) => [n.name, n]))
const TRANSIENT = new Set([
  'STARTING', 'STOPPING', 'ABORTING', 'HOLDING',
  'UNHOLDING', 'PAUSING', 'RESUMING', 'RESETTING', 'COMPLETING',
])

const HW = NODE_W / 2
const HH = NODE_H / 2
const GAP = 3 // clearance between an edge end and the node border
const ARROW = 5 // extra room at the target so the arrowhead sits clear of the border

// Chip sits nearer its source node (not the midpoint), so a reverse pair sharing a spoke
// (HOLD/UNHOLD, PAUSE/RESUME) separates to opposite ends instead of overlapping.
const CHIP_T = 0.38

// Clip a (possibly bowed) quadratic-Bézier edge to both node borders along the curve's end
// tangents, and return the path + the point (at CHIP_T) where the command chip sits.
function edgeGeom(e: ChartEdge) {
  const a = NODES.get(e.from)!
  const b = NODES.get(e.to)!
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  const cx = mx + (-dy / len) * e.bend // control point (perpendicular bow)
  const cy = my + (dx / len) * e.bend

  const p0 = border(a.x, a.y, cx - a.x, cy - a.y, 0) // leave A along the start tangent
  const p1 = border(b.x, b.y, cx - b.x, cy - b.y, ARROW) // enter B along the end tangent
  const t = CHIP_T
  const mt = 1 - t
  return {
    d: `M${p0.x} ${p0.y}Q${cx} ${cy} ${p1.x} ${p1.y}`,
    // point on the clipped quadratic at t = CHIP_T
    lx: mt * mt * p0.x + 2 * mt * t * cx + t * t * p1.x,
    ly: mt * mt * p0.y + 2 * mt * t * cy + t * t * p1.y,
  }
}

// The point on a node's border in direction (dx,dy) from its centre, plus GAP (+ pad).
function border(cx: number, cy: number, dx: number, dy: number, pad: number) {
  const len = Math.hypot(dx, dy) || 1
  const ux = dx / len
  const uy = dy / len
  const t = Math.min(HW / (Math.abs(ux) || 1e-6), HH / (Math.abs(uy) || 1e-6))
  return { x: cx + ux * (t + GAP + pad), y: cy + uy * (t + GAP + pad) }
}

interface Props {
  state?: string
  enabled: Set<string>
  connected: boolean
  busy: string | null
  onStart: () => void
  onCommand: (command: string) => void
}

export function ServiceStateChart({ state, enabled, connected, busy, onStart, onCommand }: Props) {
  // Reset hops are contextual: drawn only from the current terminal state.
  const edges = STATE_EDGES.filter((e) => !e.reset || e.from === state)

  return (
    <div
      className="relative mx-auto w-full max-w-[880px]"
      style={{ aspectRatio: `${VIEW_W} / ${VIEW_H}` }}
    >
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="h-full w-full">
        <defs>
          {(['faint', 'accent', 'transient'] as const).map((k) => (
            <marker
              key={k}
              id={`sc-arrow-${k}`}
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path
                d="M0 0 L10 5 L0 10 z"
                fill={
                  k === 'accent'
                    ? 'var(--color-accent)'
                    : k === 'transient'
                      ? 'var(--color-st-transient)'
                      : 'var(--color-edge-strong)'
                }
              />
            </marker>
          ))}
        </defs>

        {/* edges */}
        {edges.map((e, i) => {
          const g = edgeGeom(e)
          const outgoing = e.from === state
          const transiting = e.via === state
          const key = transiting ? 'transient' : outgoing ? 'accent' : 'faint'
          const stroke = transiting
            ? 'var(--color-st-transient)'
            : outgoing
              ? 'var(--color-accent)'
              : 'var(--color-edge-strong)'
          return (
            <path
              key={i}
              d={g.d}
              fill="none"
              stroke={stroke}
              strokeWidth={transiting ? 1.6 : outgoing ? 1.3 : 1}
              strokeLinecap="round"
              strokeDasharray={transiting ? '4 3' : undefined}
              markerEnd={`url(#sc-arrow-${key})`}
              className={transiting ? 'edge-flow' : undefined}
              style={{ opacity: transiting ? 1 : outgoing ? 0.9 : 0.34 }}
            >
              <title>{`${e.from} → ${e.to}${e.command ? ` (${e.command})` : ''}`}</title>
            </path>
          )
        })}

        {/* nodes — SVG rects so the border geometry is exact */}
        {STATE_NODES.map((n) => {
          const current = n.name === state
          const color = colorOf(n.name)
          return (
            <g
              key={n.name}
              opacity={current ? 1 : 0.5}
              style={current ? { filter: `drop-shadow(0 0 6px ${color})` } : undefined}
            >
              <rect
                x={n.x - HW}
                y={n.y - HH}
                width={NODE_W}
                height={NODE_H}
                rx={5}
                fill="var(--color-elev)"
                stroke={color}
                strokeWidth={current ? 1.8 : 1}
              />
              <text
                x={n.x}
                y={n.y + 0.5}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={color}
                style={{ fontSize: 9.5, fontWeight: current ? 700 : 600, letterSpacing: '0.02em' }}
              >
                {n.name}
              </text>
            </g>
          )
        })}

        {/* command chips — part of the diagram, on every command edge. Dim by default;
            lit + clickable when CommandEn allows; shows the "-ing" state while transiting. */}
        {edges.map((e, i) => {
          const g = edgeGeom(e)
          const transiting = e.via === state
          const cmd = e.command
          const live = connected && !!cmd && !transiting && enabled.has(cmd!)
          const label = transiting ? e.via! : busy && busy === cmd ? '···' : cmd
          if (!label) return null

          const danger = cmd === 'ABORT' || cmd === 'STOP'
          const w = label.length * 6 + 16
          const h = 18
          // fill / stroke / text tiers: transiting → lit → danger-lit → dim
          const fill = transiting
            ? 'var(--color-st-transient)'
            : live
              ? danger
                ? 'var(--color-danger)'
                : 'var(--color-accent)'
              : 'var(--color-panel)'
          const textFill = transiting || live ? 'var(--color-canvas)' : 'var(--color-faint)'
          const stroke = transiting
            ? 'var(--color-st-transient)'
            : live
              ? 'transparent'
              : 'var(--color-edge-strong)'
          const clickable = live && busy === null

          return (
            <g
              key={i}
              transform={`translate(${g.lx} ${g.ly})`}
              onClick={clickable ? () => (cmd === 'START' ? onStart() : onCommand(cmd!)) : undefined}
              style={{ cursor: clickable ? 'pointer' : 'default' }}
              className={transiting ? 'glow-breathe' : undefined}
            >
              <rect
                x={-w / 2}
                y={-h / 2}
                width={w}
                height={h}
                rx={h / 2}
                fill={fill}
                stroke={stroke}
                strokeWidth={0.8}
              />
              <text
                x={0}
                y={0.4}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={textFill}
                style={{ fontSize: 7.0, fontWeight: 700, letterSpacing: '0.03em' }}
              >
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

// The state's own colour as a CSS var (mirrors ui/state.ts, but as a raw value for SVG).
const STABLE_VAR: Record<string, string> = {
  IDLE: '--color-st-idle',
  EXECUTE: '--color-st-execute',
  PAUSED: '--color-st-paused',
  HELD: '--color-st-held',
  COMPLETED: '--color-st-completed',
  STOPPED: '--color-st-stopped',
  ABORTED: '--color-st-aborted',
}
function colorOf(name: string): string {
  if (TRANSIENT.has(name)) return 'var(--color-st-transient)'
  return `var(${STABLE_VAR[name] ?? '--color-st-idle'})`
}
