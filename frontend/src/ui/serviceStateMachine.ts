// The [2658-4:2022] service state machine, laid out as a symmetric "hub" chart. States
// are Table 14; the transition edges are transcribed from
// docs/POL_and_MTP_Standards_Research.md §4.3 — itself transcribed from the standard's
// Figure 4 "MTP State machine for Services (version 2022)". Rule 1: cited, not guessed.
//
// EXECUTE is the hub every transition passes through, so it sits at the centre and the
// other 6 STABLE states radiate on straight spokes: the happy path runs left→right
// (IDLE → EXECUTE → COMPLETED), the interrupt loops sit above (HELD, PAUSED — they return
// to Execute) and the terminal states below (STOPPED, ABORTED). Each spoke is a straight
// line; the command that drives it rides the line as a chip. The 9 transient "-ing" states
// each ride an edge as the `via` it momentarily passes through (Table 14). Coords are in
// the SVG's uniform VIEW_W×VIEW_H viewBox so edges clip exactly to the node borders.

// A wide, tall viewBox with a small fixed node size: this keeps the boxes compact while
// spreading them far apart on long spokes, so the chips have room and nothing crowds.
export const VIEW_W = 660
export const VIEW_H = 320
export const NODE_W = 68
export const NODE_H = 27

export interface ChartNode {
  name: string
  x: number // node centre, viewBox units
  y: number
}

export const STATE_NODES: ChartNode[] = [
  // interrupt loops — return to Execute (top row)
  { name: 'HELD', x: 70, y: 50 },
  { name: 'PAUSED', x: 590, y: 50 },
  // happy path (middle row) with the hub at centre
  { name: 'IDLE', x: 70, y: 160 },
  { name: 'EXECUTE', x: 330, y: 160 },
  { name: 'COMPLETED', x: 590, y: 160 },
  // terminal states (bottom row)
  { name: 'STOPPED', x: 70, y: 270 },
  { name: 'ABORTED', x: 590, y: 270 },
]

export interface ChartEdge {
  from: string
  to: string
  command: string | null // Command (Table 14) whose chip rides this edge; null = automatic "SC"
  via: string | null // transient state passed through (Table 14) — shown on the edge while active
  bend: number // perpendicular bow (viewBox units); 0 = straight spoke, used to split reverse pairs
  fromAny?: boolean // §4.3: reachable from any state; drawn off EXECUTE for a clean layout
  reset?: boolean // a Reset edge — drawn only when the service is actually in this `from` state
}

// Every command edge of §4.3's transition map. Restart (EXECUTE→STARTING) is omitted:
// the WG position paper recommends disabling it for ISA-88 compatibility (§4.3).
export const STATE_EDGES: ChartEdge[] = [
  { from: 'IDLE', to: 'EXECUTE', command: 'START', via: 'STARTING', bend: 0 },
  { from: 'EXECUTE', to: 'COMPLETED', command: 'COMPLETE', via: 'COMPLETING', bend: 0 },
  // interrupt loops: reverse pairs share a bend magnitude so they bow to opposite sides.
  { from: 'EXECUTE', to: 'PAUSED', command: 'PAUSE', via: 'PAUSING', bend: 30 },
  { from: 'PAUSED', to: 'EXECUTE', command: 'RESUME', via: 'RESUMING', bend: 30 },
  { from: 'EXECUTE', to: 'HELD', command: 'HOLD', via: 'HOLDING', bend: 30, fromAny: true },
  { from: 'HELD', to: 'EXECUTE', command: 'UNHOLD', via: 'UNHOLDING', bend: 30 },
  { from: 'EXECUTE', to: 'STOPPED', command: 'STOP', via: 'STOPPING', bend: 0, fromAny: true },
  { from: 'EXECUTE', to: 'ABORTED', command: 'ABORT', via: 'ABORTING', bend: 0, fromAny: true },
  // Reset edges are contextual (drawn only from the current terminal state), so they never
  // form the permanent tangle of three lines converging on IDLE.
  { from: 'COMPLETED', to: 'IDLE', command: 'RESET', via: 'RESETTING', bend: -150, reset: true },
  { from: 'STOPPED', to: 'IDLE', command: 'RESET', via: 'RESETTING', bend: 0, reset: true },
  { from: 'ABORTED', to: 'IDLE', command: 'RESET', via: 'RESETTING', bend: -92, reset: true },
]
