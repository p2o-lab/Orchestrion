import { createContext } from 'react'

/**
 * How a transition asks to change its own OR-branch priority — chart §8.
 *
 * **A context rather than a callback in `node.data`.** React Flow node data is rebuilt by the
 * builder's derive-flags effect, and a fresh function identity on every render would make that
 * effect's "did anything actually change?" comparison always false — an infinite update loop.
 * The node already knows its own `id`, so the handler needs no per-node closure.
 *
 * **Its own file** because `react-refresh/only-export-components` (rightly) refuses a context
 * exported alongside components: Fast Refresh cannot preserve it across edits.
 */
export const BranchPriority = createContext<((id: string, direction: 'up' | 'down') => void) | null>(null)
