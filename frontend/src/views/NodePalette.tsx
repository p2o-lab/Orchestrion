import { Icon } from '../ui/icons'

// What you drop onto a GRAFCET chart. START and END are singletons already on the canvas.
//   Step        — a PEA service.
//   Transition  — the guard between two steps (carries the condition).
//   AND (═)     — simultaneous branch: one transition → parallel steps, or parallel steps → one transition.
//   OR  (─)     — selection branch: one step → branch transitions, or branch transitions → one step.
export type PaletteKind = 'step' | 'transition' | 'and' | 'or'

const ITEMS: { kind: PaletteKind; label: string; hint: string }[] = [
  { kind: 'step', label: 'Step', hint: 'a PEA service' },
  { kind: 'transition', label: 'Transition', hint: 'a guard between two steps — the condition to advance' },
  { kind: 'and', label: 'AND', hint: 'simultaneous (═): parallel branches run together' },
  { kind: 'or', label: 'OR', hint: 'selection (─): one branch among several' },
]

export const DRAG_KEY = 'application/orchestrion'

function Glyph({ kind }: { kind: PaletteKind }) {
  if (kind === 'step')
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-accent">
        <Icon name="module" size={13} />
      </span>
    )
  if (kind === 'transition')
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/5">
        <span className="h-4 w-[4px] rounded-full bg-warn" />
      </span>
    )
  const lines = kind === 'and' ? 2 : 1
  const tone = kind === 'and' ? 'bg-accent' : 'bg-[#a78bfa]'
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center gap-[3px] rounded-md bg-white/5">
      {Array.from({ length: lines }).map((_, i) => (
        <span key={i} className={`h-4 w-[3px] rounded-full ${tone}`} />
      ))}
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
      <span className="ml-1 text-[11px] text-faint">drag or click to add · Step → Transition → Step; branch with AND (═) or OR (─)</span>
    </div>
  )
}
