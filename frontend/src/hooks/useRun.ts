// Driving and watching one recipe's run — M5.5(a).
//
// Polls `GET …/runs/{id}`, which has been truthful mid-run since `010` §14's P1 fix (before
// it, the engine built its own `RecipeRun` and `RunManager` held a placeholder, so a run
// reported `status:"running", steps:{}` for its entire execution and this view would have
// rendered an empty chart).
//
// **Polling, not a WebSocket.** `live.py` has one for PEA state, but there is no run WS
// (`OUTSTANDING.md` A1c) and adding one is a separate, optional increment. A poll is honest
// here: run state changes at step granularity — seconds, usually — not at the 200 ms cadence
// of a subscription, and the endpoint is a dict lookup with no I/O behind it.

import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { RunReport } from '../api/types'
import { isLive } from '../ui/runView'

/** How often a live run is re-read. Fast enough that a step change feels immediate, slow
 *  enough that a long batch is not thousands of requests an hour. */
const POLL_MS = 600

/** Backoff after a failed poll. Slower, because the likely causes — a restarted backend, a
 *  dropped connection — do not resolve in half a second, and hammering one that is not there
 *  helps nobody. But it **keeps trying**: the run is still executing on the plant, and the
 *  view has to be able to catch up again on its own. */
const POLL_ERROR_MS = 2500

export interface RunController {
  /** The latest report, or `null` when this recipe has never been run in this session. */
  report: RunReport | null
  /** A run is in flight — `running`, or `held`/`paused` with an operator intervening. */
  live: boolean
  /** A start or abort request is in flight (not the run itself). */
  busy: boolean
  /** The last request failure — a 409 for "already running" or "connect these PEAs first",
   *  a 422 for a recipe that cannot run on this project. **Not** a run failure: that is
   *  `report.error`, and it arrives through the report like any other state. */
  error: string | null
  start: () => Promise<void>
  abort: () => Promise<void>
  dismissError: () => void
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : String((e as Error)?.message ?? e)
}

/** Everything this hook holds, **keyed by the recipe it belongs to**.
 *
 *  One state object rather than three, and carrying its own `key`, so that switching recipe
 *  resets the view **during render** — `state.key !== recipeId` simply reads as "nothing
 *  here yet". The obvious alternative, `setReport(null)` at the top of an effect, is a
 *  synchronous setState inside an effect: it costs a second render pass every time and
 *  React flags it (`react-hooks/set-state-in-effect`). Deriving is both cheaper and the
 *  reason no stale report can ever be shown for the wrong recipe.
 */
interface RunSlot {
  key: number
  report: RunReport | null
  error: string | null
  /** Bumped on **every** completed poll, success or failure.
   *
   *  Load-bearing: the poll effect re-arms itself off its own dependencies, and on a failure
   *  the report object is reused by reference — so without this the dependency array would
   *  be unchanged, the effect would not re-run, and **no further timer would ever be
   *  scheduled**. One dropped request would silently end live updates for the rest of the
   *  session. Found in the 2026-09-06 audit. */
  tick: number
}

export function useRun(projectId: number, recipeId: number): RunController {
  const [slot, setSlot] = useState<RunSlot>({
    key: recipeId, report: null, error: null, tick: 0,
  })
  const [busy, setBusy] = useState(false)

  const fresh = slot.key === recipeId
  const report = fresh ? slot.report : null
  const error = fresh ? slot.error : null

  const put = useCallback(
    (patch: Partial<Omit<RunSlot, 'key'>>) =>
      setSlot((prev) => {
        const mine = prev.key === recipeId
        return {
          key: recipeId,
          report: mine ? prev.report : null,
          error: mine ? prev.error : null,
          tick: mine ? prev.tick : 0,
          ...patch,
        }
      }),
    [recipeId],
  )

  /** Adopt a run **only if nothing is already showing.**
   *
   *  The mount-time listing is asynchronous, so it can land *after* a fast `Run` click and
   *  overwrite the run just started with the older one from the listing. Guarded here rather
   *  than with a flag, because the condition is exactly "there is nothing to replace". */
  const adoptIfEmpty = useCallback(
    (found: RunReport) =>
      setSlot((prev) =>
        prev.key === recipeId && prev.report !== null
          ? prev
          : { key: recipeId, report: found, error: null, tick: 0 },
      ),
    [recipeId],
  )

  // Adopt a run that is already in flight for this recipe. A batch outlives the page that
  // started it — the engine task lives in the backend's loop — so reloading, or navigating
  // away and back, must find the run still there rather than pretend nothing is happening.
  // Same principle as the PEA connection surviving navigation (journal `005`).
  useEffect(() => {
    let cancelled = false
    api
      .listRuns(projectId)
      .then((runs) => {
        if (cancelled) return
        const mine = runs.filter((r) => r.recipe_id === recipeId)
        // Prefer a live one; otherwise show the most recent, so the last outcome is still
        // on screen instead of the view looking as though nothing ever ran.
        const adopt = mine.find((r) => isLive(r.status)) ?? mine[0]
        if (adopt) adoptIfEmpty(adopt)
      })
      .catch(() => undefined) // a listing failure must not block authoring
    return () => {
      cancelled = true
    }
  }, [projectId, recipeId, adoptIfEmpty])

  // The poll re-arms itself off `slot.tick`, which every completed attempt bumps — so it
  // keeps going **whether the last one succeeded or failed**, and stops only when the run
  // reaches a terminal status. Exactly one timer is in flight at a time.
  useEffect(() => {
    if (report === null || !isLive(report.status)) return
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .getRun(projectId, report.run_id)
        .then((next) => {
          // A good reading clears a previous complaint: a blip that recovered is not
          // something to keep telling the operator about.
          if (!cancelled) put({ report: next, error: null, tick: slot.tick + 1 })
        })
        .catch((e) => {
          // A poll failure is **not** a run failure — the run lives in the backend and
          // carries on. So surface it and KEEP POLLING, more slowly: the earlier version
          // stopped for good here, and a single dropped request during a two-hour batch
          // froze the view with no way back short of a reload.
          if (!cancelled) put({ error: message(e), tick: slot.tick + 1 })
        })
    }, error === null ? POLL_MS : POLL_ERROR_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [report, projectId, put, slot.tick, error])

  const start = useCallback(async () => {
    setBusy(true)
    put({ error: null })
    try {
      const handle = await api.startRun(projectId, recipeId)
      put({ report: await api.getRun(projectId, handle.run_id), error: null })
    } catch (e) {
      put({ error: message(e) })
    } finally {
      setBusy(false)
    }
  }, [projectId, recipeId, put])

  const abort = useCallback(async () => {
    if (report === null) return
    setBusy(true)
    try {
      await api.abortRun(projectId, report.run_id)
      // Deliberately not optimistic: `abort()` only asks the engine to stop after its
      // current tick, and it commands no PEA (step model §10), so the honest thing is to
      // let the next poll report what actually happened — including what it left running.
      put({ report: await api.getRun(projectId, report.run_id) })
    } catch (e) {
      put({ error: message(e) })
    } finally {
      setBusy(false)
    }
  }, [projectId, report, put])

  const dismissError = useCallback(() => put({ error: null }), [put])

  return {
    report,
    live: report !== null && isLive(report.status),
    busy,
    error,
    start,
    abort,
    dismissError,
  }
}
