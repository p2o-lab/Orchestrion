import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Icon } from '../ui/icons'

// A step draws **no branch symbol of any kind.** [IEC 60848:2013] §6.2.3: a selection of
// sequences "is represented by as many simultaneously enabled transitions as possible
// evolutions" — the fan-out of transitions *is* the notation, and the standard gives it no
// glyph. The synchronization symbol of Table 2 [9] belongs to the transition, never here.
// (Unit 10 first shipped an invented single "OR rail"; it was deleted once the symbol tables
// were read — `010` §12.)

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
   *  beginning). [IEC 60848:2013] Table 1 **[3]**: "Initial step: this symbol means that this
   *  step participates in the initial situation." The clause names the symbol but does not
   *  describe it in words — the glyph is a figure — so the **double border** we draw is
   *  `[SEARCHED]`, standard GRAFCET practice rather than a quotable line. There is no START
   *  node; the border *is* the marker (chart §1, §2). */
  isInitial?: boolean
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
