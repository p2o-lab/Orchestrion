import { useContext } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { Condition } from '../api/types'
import type { BarSpan } from '../ui/recipeGraph'
import { BranchPriority } from './branchPriority'

/**
 * The synchronization symbol — chart §6. `[CITED]` [IEC 60848:2013] Table 2 **[9]**: "When
 * several steps are connected to the same transition, the directed links from and/or to these
 * steps are grouped, to succeed or precede the synchronization symbol represented by **two
 * parallel horizontal lines**." Hence exactly two, always — it is one symbol, not a family, so
 * there is nothing here to parameterise. Drawn by the transition that owns it, spanning its steps.
 *
 * Table 2 [9] says "horizontal", which is what perpendicular means on a top→bottom chart
 * (Table 3 [11]). Our canvas runs left→right with arrowheads — [11]'s sanctioned deviation —
 * so the same symbol turns 90° with the flow.
 */
function BranchBar({ span, side }: { span: BarSpan; side: 'left' | 'right' }) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute top-1/2 flex gap-[3px]"
      style={{
        [side]: -14,
        height: span.height,
        transform: `translateY(calc(-50% + ${span.offsetY}px))`,
      }}
    >
      {[0, 1].map((i) => (
        <span key={i} className="w-[3px] rounded-full bg-accent" style={{ height: '100%' }} />
      ))}
    </span>
  )
}

// The chart's transition node — `docs/POL_Recipe_Chart_GRAFCET.md` §1 and §4.
//
// **A transition is a node, not an arrow.** §4.3.3: "associated with each transition, the
// transition-condition is a logical expression which is true or false". The receptivity lives
// here; directed links carry nothing (§3.1.2). Drawn as a short bar crossing the link — the
// glyph seen in Figure 2 — with the condition summary beside it. Double-click to edit.
//
// **AndNode / OrNode / StartNode / EndNode were deleted at `010` unit 9.** AND and OR are
// **link multiplicity** (§4.3.2), not elements. AND gets a symbol — Table 2 [9]'s two parallel
// lines, rendered below *from* the links — while OR gets none at all (§6.2.3). The initial step
// is inferred and drawn with a double border (`StepNode`), and the end of a branch is an
// unwired output (§3), not a node.

export interface TransitionNodeData {
  condition?: Condition // the receptivity; the engine transition carries it
  label?: string // human summary (e.g. "Temp > 80"); computed by the builder
  /** No successor — this branch ends here (§3, a "pit transition"). Drawn with a solid cap so
   *  a finished branch is never mistaken for one still being wired. */
  isPit?: boolean
  /** A continuous from-step needs a real receptivity; `Always` would complete it instantly
   *  (§4). Until the author supplies one the transition is visibly incomplete. */
  needsCondition?: boolean
  /** The synchronization symbols this transition draws when several steps precede it
   *  (§6.2.7) or succeed it (§6.2.6) — Table 2 [9]. Computed by `recipeGraph.barSpans`;
   *  decoration over link multiplicity, never structure. */
  barIn?: BarSpan
  barOut?: BarSpan
  /** OR-branch priority (chart §8) — the sort key that becomes this transition's position in
   *  `MasterRecipe.transitions`, which is what the engine arbitrates on. Not a wire field. */
  priority?: number
  /** Where this transition sits among the ones leaving a common step, when there are several.
   *  Absent for a plain series — nothing to arbitrate. Computed by `recipeGraph.branchRanks`. */
  rank?: { rank: number; of: number }
  [key: string]: unknown
}

/**
 * The OR-branch priority badge — chart §8.
 *
 * Shown only on a transition that is one of **several** leaving the same step (a selection,
 * §6.2.3); a plain series has nothing to arbitrate. The engine walks
 * `MasterRecipe.transitions` in order and the first eligible transition to claim a step wins,
 * so this rank *is* the arbitration — it was previously an invisible artefact of array order.
 *
 * **▲▼ rather than drag.** §8 asked for a "draggable ①②③", but on a canvas node pointer-down
 * already means *move the node* — React Flow owns it, and a drag-to-reorder would fight the
 * gesture that positions the chart. `nodrag` keeps the buttons from starting a node drag.
 */
export function PriorityBadge({
  rank,
  of,
  onMove,
}: {
  rank: number
  of: number
  onMove?: (direction: 'up' | 'down') => void
}) {
  const circled = '①②③④⑤⑥⑦⑧⑨'[rank - 1] ?? `${rank}`
  return (
    <span
      className="nodrag absolute -top-3 left-0 flex items-center gap-0.5 rounded-full border border-warn/40 bg-panel px-1.5 py-0.5"
      title={`Branch ${rank} of ${of} — lower numbers are tried first`}
    >
      <span className="text-[11px] leading-none text-warn">{circled}</span>
      <button
        type="button"
        aria-label={`Raise branch ${rank} priority`}
        disabled={rank === 1}
        onClick={() => onMove?.('up')}
        className="px-0.5 text-[9px] leading-none text-faint transition enabled:hover:text-ink disabled:opacity-30"
      >
        ▲
      </button>
      <button
        type="button"
        aria-label={`Lower branch ${rank} priority`}
        disabled={rank === of}
        onClick={() => onMove?.('down')}
        className="px-0.5 text-[9px] leading-none text-faint transition enabled:hover:text-ink disabled:opacity-30"
      >
        ▼
      </button>
    </span>
  )
}

export function TransitionNode({ id, data, selected }: NodeProps) {
  const d = data as TransitionNodeData
  const move = useContext(BranchPriority)
  const set = Boolean(d.label)
  return (
    <div className="relative flex items-center gap-2">
      {d.rank && (
        <PriorityBadge
          rank={d.rank.rank}
          of={d.rank.of}
          onMove={move ? (direction) => move(id, direction) : undefined}
        />
      )}
      {/* Table 2 [9] — two parallel lines spanning the steps this transition synchronises
          (§6.2.7) or activates in parallel (§6.2.6); both sides at once is §6.2.8. */}
      {d.barIn ? <BranchBar span={d.barIn} side="left" /> : null}
      {d.barOut ? <BranchBar span={d.barOut} side="right" /> : null}
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-0 !bg-warn" />
      {/* the receptivity bar — a tick across the directed link */}
      <div className={`h-9 w-[4px] rounded-full bg-warn ${selected ? 'ring-2 ring-warn/40' : ''}`} />
      <span
        className={`whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium ${
          set
            ? 'border-warn/40 bg-warn/10 text-warn'
            : d.needsCondition
              ? 'border-danger/50 bg-danger/10 text-danger'
              : 'border-dashed border-edge-strong bg-elev text-faint'
        }`}
      >
        {set ? d.label : d.needsCondition ? 'condition required' : 'set condition…'}
      </span>
      {d.isPit ? (
        // §3 — the branch ends here. A solid cap, deliberately distinct from the faded stub
        // of a transition that simply has not been wired yet.
        <span
          className="ml-0.5 h-6 w-[3px] rounded-full bg-st-completed"
          title="End of this branch"
        />
      ) : null}
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-0 !bg-warn" />
    </div>
  )
}
