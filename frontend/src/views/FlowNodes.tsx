import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { Condition } from '../api/types'

// GRAFCET nodes. The chart alternates STEPS and TRANSITIONS; START marks the initial step.
//
// A TRANSITION is the GRAFCET receptivity: a short bar crossing the link, carrying the guard
// condition. It fires when every upstream step is active and the condition is true. Rendered as a
// vertical bar (flow runs left→right) with the condition summary beside it. Double-click to edit.
export interface TransitionNodeData {
  condition?: Condition // the receptivity guard; the engine transition carries it
  label?: string // human summary of the condition (e.g. "✓ COMPLETED"); computed by the builder
  [key: string]: unknown
}

export function TransitionNode({ data, selected }: NodeProps) {
  const d = data as TransitionNodeData
  const set = Boolean(d.label)
  return (
    <div className="flex items-center gap-2">
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-0 !bg-warn" />
      {/* the transition bar (GRAFCET receptivity symbol) */}
      <div className={`h-9 w-[4px] rounded-full bg-warn ${selected ? 'ring-2 ring-warn/40' : ''}`} />
      <span
        className={`whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium ${
          set ? 'border-warn/40 bg-warn/10 text-warn' : 'border-dashed border-edge-strong bg-elev text-faint'
        }`}
      >
        {set ? d.label : 'set condition…'}
      </span>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-0 !bg-warn" />
    </div>
  )
}

// The GRAFCET branch junctions — pure synchronisation/selection, they carry NO condition.
//   AND (═, divergence/convergence en ET) — simultaneous: one transition splits to parallel steps,
//       or parallel steps synchronise into one transition. Drawn as the DOUBLE line.
//   OR  (─, divergence/convergence en OU) — selection: one step opens onto branch transitions, or
//       branch transitions merge into one step. Drawn as the SINGLE line.
// Both connect on either side (a bar is a divergence or a convergence depending on how it is wired).
function Bar({ lines, tone, dot, label }: { lines: 1 | 2; tone: string; dot: string; label: string }) {
  return (
    <div className="relative flex items-center gap-[3px]">
      <Handle type="target" position={Position.Left} className={`!h-2.5 !w-2.5 !border-0 ${dot}`} />
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={`h-14 w-[4px] rounded-full ${tone}`} />
      ))}
      <span className="absolute left-1/2 top-full mt-1 -translate-x-1/2 text-[9px] font-bold uppercase tracking-wide text-faint">{label}</span>
      <Handle type="source" position={Position.Right} className={`!h-2.5 !w-2.5 !border-0 ${dot}`} />
    </div>
  )
}

export function AndNode() {
  return <Bar lines={2} tone="bg-accent" dot="!bg-accent" label="and" />
}
export function OrNode() {
  return <Bar lines={1} tone="bg-[#a78bfa]" dot="!bg-[#a78bfa]" label="or" />
}

// START — the initial step marker (GRAFCET's double-bordered initial step). Active when the recipe
// begins; it has no preceding transition and links straight to the first step. Non-deletable.
export function StartNode() {
  return (
    <div className="rounded-lg border-2 border-double border-st-completed bg-elev px-3.5 py-1.5 text-st-completed shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)] ring-2 ring-st-completed/20">
      <span className="text-xs font-bold uppercase tracking-wide">Start</span>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-0 !bg-st-completed" />
    </div>
  )
}
