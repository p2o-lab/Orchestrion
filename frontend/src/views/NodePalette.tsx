import { Icon } from '../ui/icons'

export type PaletteKind = 'step' | 'and' | 'or'

const ITEMS: { kind: PaletteKind; label: string; hint: string }[] = [
  { kind: 'step', label: 'Step', hint: 'a PEA service' },
  { kind: 'and', label: 'AND', hint: 'parallel — split runs all, merge waits for all' },
  { kind: 'or', label: 'OR', hint: 'exclusive — split takes one, merge passes through' },
]

export const DRAG_KEY = 'application/orchestrion'

// step = a block; AND = two lines; OR = one line.
function Glyph({ kind }: { kind: PaletteKind }) {
  if (kind === 'step')
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-accent">
        <Icon name="module" size={13} />
      </span>
    )
  const lines = kind === 'and' ? 2 : 1
  const tone = kind === 'and' ? 'bg-accent' : 'bg-warn'
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
      <span className="ml-1 text-[11px] text-faint">drag onto the canvas, or click to drop in the middle</span>
    </div>
  )
}
