import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { Condition } from '../api/types'
import type { BarSpan } from '../ui/recipeGraph'

/**
 * A branch bar — chart §6. Drawn by the node that owns it, spanning its branches, which is
 * GRAFCET's stacked-marks convention rather than fanning edges out of a point.
 *
 * `lines={2}` is the AND (simultaneous) bar a transition draws; `lines={1}` is the OR
 * (selection) rail a step draws. ⚠ **`[OURS]` and unverified** — IEC 60848 §5's symbol tables
 * were never read (`BLOCKED ON STANDARD`), so double-vs-single is from memory.
 */
function BranchBar({ span, side, lines, tone }: {
  span: BarSpan
  side: 'left' | 'right'
  lines: 1 | 2
  tone: string
}) {
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
      {Array.from({ length: lines }).map((_, i) => (
        <span key={i} className={`w-[3px] rounded-full ${tone}`} style={{ height: '100%' }} />
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
// **link multiplicity** (§4.3.2), not elements, so the bars are a drawing convention that
// unit 10 renders *from* the links. The initial step is inferred and drawn with a double
// border (`StepNode`), and the end of a branch is an unwired output (§3), not a node.

export interface TransitionNodeData {
  condition?: Condition // the receptivity; the engine transition carries it
  label?: string // human summary (e.g. "Temp > 80"); computed by the builder
  /** No successor — this branch ends here (§3, a "pit transition"). Drawn with a solid cap so
   *  a finished branch is never mistaken for one still being wired. */
  isPit?: boolean
  /** A continuous from-step needs a real receptivity; `Always` would complete it instantly
   *  (§4). Until the author supplies one the transition is visibly incomplete. */
  needsCondition?: boolean
  /** The AND bars this transition draws when it gathers or opens onto several steps (§6).
   *  Computed by `recipeGraph.barSpans` — decoration over link multiplicity, never structure. */
  barIn?: BarSpan
  barOut?: BarSpan
  [key: string]: unknown
}

export function TransitionNode({ data, selected }: NodeProps) {
  const d = data as TransitionNodeData
  const set = Boolean(d.label)
  return (
    <div className="relative flex items-center gap-2">
      {/* AND — simultaneous. A double bar spanning the steps it synchronises or launches. */}
      {d.barIn ? <BranchBar span={d.barIn} side="left" lines={2} tone="bg-accent" /> : null}
      {d.barOut ? <BranchBar span={d.barOut} side="right" lines={2} tone="bg-accent" /> : null}
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
