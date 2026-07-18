// A colour-coded live-state badge — [2658-4 Table 14]. Transient states pulse;
// the large variant carries a soft glow in the state's own colour.

import { stateStyle } from './state'

export function StatePill({ state, big }: { state: string | undefined; big?: boolean }) {
  const { cls, transient } = stateStyle(state)
  return (
    <span
      className={
        `inline-flex items-center gap-2 rounded-full border font-semibold tracking-wide ${cls} ` +
        (big
          ? 'px-4 py-1.5 text-sm shadow-[0_0_24px_-6px] shadow-current'
          : 'px-3 py-1 text-xs')
      }
    >
      <span
        className={`rounded-full bg-current ${big ? 'h-2 w-2' : 'h-1.5 w-1.5'} ${
          transient ? 'pulse-dot' : ''
        }`}
      />
      {state ?? 'UNKNOWN'}
    </span>
  )
}
