import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Icon } from '../ui/icons'

// A recipe step, rendered as our own Tailwind card (React Flow only positions/connects it).
// `data` carries both the display strings and the underlying step fields, so the builder can
// rebuild the MasterRecipe on save. Handles (left = target, right = source) are wired in 2c.
export interface StepNodeData {
  pea_id: number
  service: string
  procedure_id: number
  params: Record<string, number>
  pea: string // display: PEA name
  procedure: string // display: procedure name
  [key: string]: unknown
}

export function StepNode({ data, selected }: NodeProps) {
  const d = data as StepNodeData
  return (
    <div
      className={`min-w-[168px] rounded-xl border bg-elev px-3.5 py-3 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)] transition ${
        selected ? 'border-accent ring-2 ring-accent/25' : 'border-edge-strong'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-0 !bg-accent" />
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-accent/15 text-accent">
          <Icon name="module" size={13} />
        </span>
        <span className="truncate text-sm font-semibold text-ink">{d.service}</span>
      </div>
      <div className="mt-2 truncate text-xs text-dim">{d.procedure}</div>
      <div className="mt-0.5 truncate text-[10px] uppercase tracking-wide text-faint">{d.pea}</div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-0 !bg-accent" />
    </div>
  )
}
