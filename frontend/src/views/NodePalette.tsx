import { Icon } from '../ui/icons'

// The two things you drop onto a GRAFCET chart. START and END are singletons already on the canvas.
// Branching is not a block — it emerges from the wiring: one transition → several steps is a
// simultaneous (AND) split; one step → several transitions is a selection (OR).
export type PaletteKind = 'step' | 'transition'

const ITEMS: { kind: PaletteKind; label: string; hint: string }[] = [
  { kind: 'step', label: 'Step', hint: 'a PEA service' },
  { kind: 'transition', label: 'Transition', hint: 'a guard between two steps — the condition to advance' },
]

export const DRAG_KEY = 'application/orchestrion'

function Glyph({ kind }: { kind: PaletteKind }) {
  if (kind === 'step')
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-accent">
        <Icon name="module" size={13} />
      </span>
    )
  // transition = the GRAFCET receptivity bar
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
        drag or click to add · Step → Transition → Step alternate · one transition to many steps = parallel, one step to many
        transitions = choice
      </span>
    </div>
  )
}
