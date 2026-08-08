import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Icon } from '../ui/icons'
import type { BarSpan } from '../ui/recipeGraph'

/** The OR (selection) rail — a **single** line, against AND's double (chart §6).
 *  ⚠ `[OURS]`: IEC 60848 §5's symbol tables are unread, so single-vs-double is from memory. */
function SelectionRail({ span, side }: { span: BarSpan; side: 'left' | 'right' }) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute top-1/2 w-[3px] rounded-full bg-[#a78bfa]"
      style={{
        [side]: -14,
        height: span.height,
        transform: `translateY(calc(-50% + ${span.offsetY}px))`,
      }}
    />
  )
}

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
  /** This is the recipe's initial step — the one no transition targets, inferred by
   *  `recipeGraph.initialStepId` ([IEC 61512-1] item 1337: a procedure has *a* defined
   *  beginning). GRAFCET draws it with a **double border**, seen in IEC 60848 Figure 2.
   *  There is no START node; the border *is* the marker (chart §1, §2). */
  isInitial?: boolean
  /** The OR rails this step draws when several transitions leave it (divergence) or arrive
   *  (convergence) — §6. Computed by `recipeGraph.barSpans`; decoration, never structure. */
  barIn?: BarSpan
  barOut?: BarSpan
  [key: string]: unknown
}

export function StepNode({ data, selected }: NodeProps) {
  const d = data as StepNodeData
  return (
    <div
      className={`relative min-w-[168px] bg-elev px-3.5 py-3 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)] transition ${
        d.isInitial
          ? // the double-bordered initial step: an inner rule inset from the outer edge
            'rounded-xl border-2 border-double border-st-completed ring-2 ring-st-completed/20'
          : selected
            ? 'rounded-xl border border-accent ring-2 ring-accent/25'
            : 'rounded-xl border border-edge-strong'
      }`}
    >
      {d.barIn ? <SelectionRail span={d.barIn} side="left" /> : null}
      {d.barOut ? <SelectionRail span={d.barOut} side="right" /> : null}
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
