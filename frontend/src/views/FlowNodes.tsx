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
