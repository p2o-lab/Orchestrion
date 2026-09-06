import { Icon } from '../ui/icons'
import type { BranchAction, NodeKind } from '../ui/recipeGraph'
import { branchActionFor } from '../ui/recipeGraph'

// What you drop onto the chart — `docs/POL_Recipe_Chart_GRAFCET.md` §1.
//
// **Two kinds. Nothing else.** §4.3.2/§4.3.3 close the element list at step · transition ·
// directed link · transition-condition · action. So there is nothing else *to* drop:
//   • AND / OR were removed — they are **link multiplicity** (§4.3.2), drawn
//     from the links themselves, so branching is authored by *wiring*, not by placing a node.
//     The branch *actions* below (§7) build that wiring for you — they still create
//     no new node type, only a step or a transition plus the link.
//   • START / END likewise: the initial step is inferred and double-bordered (§2), and a
//     branch ends by leaving a transition's output unwired (§3).
export type PaletteKind = 'step' | 'transition'

const ITEMS: { kind: PaletteKind; label: string; hint: string }[] = [
  { kind: 'step', label: 'Step', hint: 'a PEA service procedure to run' },
  {
    kind: 'transition',
    label: 'Transition',
    hint: 'the receptivity between two steps — the condition to advance',
  },
]

export const DRAG_KEY = 'application/orchestrion'

function Glyph({ kind }: { kind: PaletteKind }) {
  if (kind === 'step')
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-accent">
        <Icon name="module" size={13} />
      </span>
    )
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/5">
      <span className="h-4 w-[4px] rounded-full bg-warn" />
    </span>
  )
}

// The two branch actions — §7. Each is enabled **only** on the node kind that can legally open
// it, so the palette teaches §4.3.2's link multiplicity instead of letting you violate it:
// a parallel branch needs a transition (§6.2.6), a selection branch needs a step (§6.2.3).
const BRANCHES: { action: BranchAction; label: string; needs: NodeKind; hint: string }[] = [
  {
    action: 'parallel',
    label: '+ parallel branch',
    needs: 'transition',
    hint: 'runs another step at the same time — adds a step after this transition (§6.2.6)',
  },
  {
    action: 'selection',
    label: '+ selection branch',
    needs: 'step',
    hint: 'an alternative route — adds another transition off this step (§6.2.3)',
  },
]

export function NodePalette({
  onQuickAdd,
  selectedKind,
  onBranch,
}: {
  onQuickAdd: (kind: PaletteKind) => void
  /** The kind of the single selected node, or `null` for none / several. */
  selectedKind: NodeKind | null
  onBranch: (action: BranchAction) => void
}) {
  const allowed = branchActionFor(selectedKind)
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-edge bg-panel/30 px-8 py-2.5">
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-faint">Blocks</span>
      {ITEMS.map(({ kind, label, hint }) => (
        <div
          key={kind}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData(DRAG_KEY, kind)
            e.dataTransfer.effectAllowed = 'move'
          }}
          onClick={() => onQuickAdd(kind)}
          title={`Drag onto the canvas — ${hint}`}
          className="flex cursor-grab items-center gap-2 rounded-lg border border-edge bg-elev px-2.5 py-1.5 transition hover:-translate-y-0.5 hover:border-accent/40 active:cursor-grabbing"
        >
          <Glyph kind={kind} />
          <span className="text-sm font-medium text-ink">{label}</span>
        </div>
      ))}
      <span className="mx-1 h-5 w-px bg-edge" aria-hidden />
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-faint">Branch</span>
      {BRANCHES.map(({ action, label, needs, hint }) => {
        const enabled = allowed === action
        return (
          <button
            key={action}
            type="button"
            disabled={!enabled}
            onClick={() => onBranch(action)}
            title={enabled ? hint : `Select a ${needs} first — ${hint}`}
            className={`rounded-lg border px-2.5 py-1.5 text-sm font-medium transition ${
              enabled
                ? 'border-accent/40 bg-elev text-ink hover:-translate-y-0.5 hover:border-accent'
                : 'cursor-not-allowed border-edge bg-elev/40 text-faint'
            }`}
          >
            {label}
          </button>
        )
      })}
      <span className="ml-1 text-[11px] text-faint">
        {allowed === null
          ? 'drag or click to add · select a step or a transition to branch from it'
          : allowed === 'parallel'
            ? 'transition selected — a parallel branch runs another step alongside'
            : 'step selected — a selection branch offers an alternative route'}
      </span>
    </div>
  )
}
