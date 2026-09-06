import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Icon } from '../ui/icons'
import type { StepPhase } from '../ui/runView'

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
  /** Where this step is in a live run — `ui/runView.ts`. Absent when nothing is running.
   *  The four real values are the **engine's** `StepState` (step model §8), not UI words;
   *  `pending` is the one addition, and it means "the run has not reached this step". */
  runPhase?: StepPhase
  /** The latched Final State, a [2658-4 Table 14] name, once the step has terminated. */
  terminal?: string
  /** That Final State was STOPPED or ABORTED — the non-recoverable levels. */
  abnormal?: boolean
  /** `HELD` / `PAUSED` — an operator is intervening on this step right now. */
  interrupted?: string
  [key: string]: unknown
}

/** How each run phase reads on the canvas.
 *
 *  `terminated` is the one that earns its place: the step has **finished** but its
 *  transition has not fired, so the run is sitting on that receptivity. Before the four
 *  step states existed there was no way to draw the difference between "still working" and
 *  "finished, waiting" — which is exactly the question an operator asks first.
 */
const PHASE: Record<StepPhase, { ring: string; chip: string; label: string }> = {
  pending: { ring: '', chip: '', label: '' },
  running: {
    ring: 'ring-2 ring-st-execute/50 border-st-execute',
    chip: 'bg-st-execute/15 text-st-execute',
    label: 'running',
  },
  completing: {
    ring: 'ring-2 ring-warn/50 border-warn',
    chip: 'bg-warn/15 text-warn',
    label: 'completing',
  },
  terminated: {
    ring: 'ring-2 ring-st-completed/50 border-st-completed',
    chip: 'bg-st-completed/15 text-st-completed',
    label: 'finished — waiting',
  },
  done: {
    ring: 'border-st-completed/50',
    chip: 'bg-white/6 text-faint',
    label: 'done',
  },
}

export function StepNode({ data, selected }: NodeProps) {
  const d = data as StepNodeData
  const phase = d.runPhase ?? 'pending'
  const running = phase === 'running' || phase === 'completing'
  // An interrupted step outranks its phase, and that is the whole point: HELD is neither
  // acting nor final, so the engine leaves it `running` — it would otherwise pulse green as
  // "working" while it is in fact the one step waiting for an operator (audit 2026-09-06).
  const tone = d.interrupted
    ? { ring: 'ring-2 ring-st-held/60 border-st-held', chip: 'bg-st-held/15 text-st-held',
        label: d.interrupted.toLowerCase() }
    : d.abnormal
      ? { ring: 'ring-2 ring-danger/50 border-danger', chip: 'bg-danger/15 text-danger',
          label: d.terminal ?? 'failed' }
      : PHASE[phase]

  return (
    <div
      className={`relative min-w-[168px] bg-elev px-3.5 py-3 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)] transition ${
        // A live run outranks selection and the initial-step border: while something is
        // executing, *where the run is* is the thing you are looking at.
        tone.ring
          ? `rounded-xl border ${tone.ring}`
          : d.isInitial
            ? // the double-bordered initial step: an inner rule inset from the outer edge
              'rounded-xl border-2 border-double border-st-completed ring-2 ring-st-completed/20'
            : selected
              ? 'rounded-xl border border-accent ring-2 ring-accent/25'
              : 'rounded-xl border border-edge-strong'
      } ${phase === 'pending' && d.runPhase !== undefined ? 'opacity-55' : ''}`}
    >
      {tone.label && (
        <span
          className={`absolute -top-2.5 right-2 flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wider ${tone.chip}`}
          title={d.terminal ? `latched final state: ${d.terminal}` : undefined}
        >
          {running && <span className="h-1 w-1 rounded-full bg-current pulse-dot" />}
          {tone.label}
        </span>
      )}
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
