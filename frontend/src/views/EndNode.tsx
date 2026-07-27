import { Handle, Position } from '@xyflow/react'

// The recipe's terminal marker. An edge into it becomes a transition to the `END` sentinel,
// which finishes that branch (the engine completes once nothing is active). Non-deletable.
export function EndNode() {
  return (
    <div className="flex items-center gap-1.5 rounded-full border-2 border-st-completed bg-elev px-3.5 py-1.5 text-st-completed shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)]">
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-0 !bg-st-completed" />
      <span className="text-xs font-bold uppercase tracking-wide">End</span>
    </div>
  )
}
