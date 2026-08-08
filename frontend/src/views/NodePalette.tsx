import { Icon } from '../ui/icons'

// What you drop onto the chart — `docs/POL_Recipe_Chart_GRAFCET.md` §1.
//
// **Two kinds. Nothing else.** §4.3.2/§4.3.3 close the element list at step · transition ·
// directed link · transition-condition · action. So there is nothing else *to* drop:
//   • AND / OR were removed at `010` unit 9 — they are **link multiplicity** (§4.3.2), drawn
//     from the links themselves, so branching is authored by *wiring*, not by placing a node.
//     Palette actions that build the wiring for you arrive in unit 11 (§7).
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

export function NodePalette({ onQuickAdd }: { onQuickAdd: (kind: PaletteKind) => void }) {
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
      <span className="ml-1 text-[11px] text-faint">
        drag or click to add · steps and transitions alternate · branch by wiring several links to
        one node · leave a transition's output free to end that branch
      </span>
    </div>
  )
}
