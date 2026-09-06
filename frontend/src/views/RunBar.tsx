// The run strip above the chart — M5.5(a): launch, abort, and what the run is doing.
//
// The chart itself shows *where* the run is (M5.5b); this shows *how it is going* and owns
// the controls. Every word it renders comes from `ui/runView.ts`, which maps the engine's
// own vocabulary rather than inventing one beside it.

import { useEffect, useState } from 'react'
import type { RunController } from '../hooks/useRun'
import { elapsedSeconds, isFailure, summarizeRun } from '../ui/runView'
import type { RunStatus } from '../api/types'
import { Button, Spinner } from '../ui/primitives'
import { Icon } from '../ui/icons'

/** Status → pill styling. Literal class strings so Tailwind's scanner keeps them, the same
 *  reason `ui/state.ts` writes them out for the [2658-4] service states. */
const STATUS_TONE: Record<RunStatus, string> = {
  running: 'text-st-execute border-st-execute/35 bg-st-execute/10',
  held: 'text-st-held border-st-held/35 bg-st-held/10',
  paused: 'text-st-paused border-st-paused/35 bg-st-paused/10',
  completed: 'text-st-completed border-st-completed/35 bg-st-completed/10',
  failed: 'text-danger border-danger/35 bg-danger/10',
  aborted: 'text-danger border-danger/35 bg-danger/10',
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Re-render once a second **only while the run is live**, so the elapsed clock ticks
 *  without the whole builder re-rendering for a run that finished an hour ago. */
function useTick(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

export function RunBar({
  run,
  dirty,
  onSave,
}: {
  run: RunController
  /** The canvas has unsaved semantic edits — `Run` would execute the *stored* chart. */
  dirty: boolean
  onSave: () => void
}) {
  const now = useTick(run.live)
  const { report } = run

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-edge bg-panel/20 px-8 py-2.5">
      {run.live ? (
        <Button variant="danger" small onClick={run.abort} disabled={run.busy}>
          {run.busy ? <Spinner className="h-4 w-4" /> : <Icon name="power" size={15} />}
          Abort
        </Button>
      ) : (
        <Button
          variant="primary"
          small
          onClick={run.start}
          disabled={run.busy || dirty}
          title={dirty ? 'Save first — Run executes the stored recipe, not the canvas' : undefined}
        >
          {run.busy ? <Spinner className="h-4 w-4" /> : <Icon name="power" size={15} />}
          Run
        </Button>
      )}

      {/* Unsaved edits block Run rather than silently running a different chart. The
          shortcut saves, so the operator is one click from being able to run. */}
      {dirty && !run.live && (
        <button
          onClick={onSave}
          className="rounded-md border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn transition hover:bg-warn/20"
        >
          unsaved changes — save to run
        </button>
      )}

      {report && (
        <>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_TONE[report.status]}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full bg-current ${run.live ? 'pulse-dot' : ''}`}
            />
            {report.status}
          </span>
          <span className="text-xs text-dim">{summarizeRun(report)}</span>
          <span className="font-mono text-xs tabular-nums text-faint">
            {clock(elapsedSeconds(report, now))}
          </span>
          <span className="text-[11px] text-faint">run #{report.run_id}</span>
        </>
      )}

      <div className="ml-auto flex items-center gap-2">
        {/* A request failure (409 "connect these PEAs first", 422, a dead backend) — NOT a
            run failure, which arrives as `report.error` and is shown in the status line. */}
        {run.error && (
          <span
            className="max-w-md truncate rounded-md border border-danger/40 bg-danger/10 px-2 py-1 text-xs text-danger"
            title={run.error}
            onClick={run.dismissError}
            role="button"
          >
            {run.error}
          </span>
        )}
        {report && isFailure(report.status) && report.error && (
          <span
            className="max-w-md truncate text-xs text-danger"
            title={report.error}
          >
            {report.error}
          </span>
        )}
      </div>
    </div>
  )
}
