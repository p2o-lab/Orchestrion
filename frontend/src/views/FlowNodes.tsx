import { Handle, Position } from '@xyflow/react'

// The two gateways. AND = a DOUBLE line (parallel/simultaneous); OR = a SINGLE line
// (exclusive/selection). Each works as a split (1 in → many out) or a merge (many in → 1 out)
// depending on how it is wired — the line count is the only difference.
function Gate({
  lines,
  bar,
  dot,
  text,
  glow,
  label,
}: {
  lines: 1 | 2
  bar: string
  dot: string
  text: string
  glow: string
  label: string
}) {
  return (
    <div className={`relative flex items-center gap-[3px] ${glow}`}>
      <Handle type="target" position={Position.Left} className={`!h-2.5 !w-2.5 !border-0 ${dot}`} />
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={`h-16 w-[3px] rounded-full ${bar}`} />
      ))}
      <span className={`absolute left-1/2 top-full mt-1 -translate-x-1/2 text-[9px] font-bold uppercase tracking-wide ${text}`}>
        {label}
      </span>
      <Handle type="source" position={Position.Right} className={`!h-2.5 !w-2.5 !border-0 ${dot}`} />
    </div>
  )
}

export function AndNode() {
  return <Gate lines={2} bar="bg-accent" dot="!bg-accent" text="text-accent" glow="[filter:drop-shadow(0_0_8px_rgba(124,156,255,0.5))]" label="and" />
}

export function OrNode() {
  return <Gate lines={1} bar="bg-warn" dot="!bg-warn" text="text-warn" glow="[filter:drop-shadow(0_0_8px_rgba(251,191,36,0.5))]" label="or" />
}
