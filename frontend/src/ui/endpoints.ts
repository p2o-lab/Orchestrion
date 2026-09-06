// Endpoint collision detection — pure, framework-free, tested.
//
// Two PEAs in one project on the same OPC UA endpoint are two rows talking to **one
// physical server**. That is not fatal on its own, and the backend deliberately lets the
// import through (`peas.py::_endpoint_conflict` returns a warning, never a refusal): the
// condition is recoverable, and the run path already fails loudly on the consequence —
// `ensure_idle` finds the shared service in `EXECUTE` and refuses the second step by name,
// because its test is ownership, not reachability.
//
// So this is the *visible* half. The import dialog warns at the moment it happens; this
// backs the persistent badge on the PEA cards, because the conflict outlives the dialog.
//
// **This mirrors a server rule, so it can drift from it** — which is exactly how the
// nested-`Always` gap survived (the builder walked the tree, the server checked only the
// outermost node, and the server was the lax one). Both sides normalise the same way, and
// share the same stated limitation.

import type { PeaSummary } from '../api/types'

/**
 * The form two endpoints are compared in — trimmed, no trailing slash, lower-cased.
 * Mirrors `peas.py::_normalise_endpoint`.
 *
 * Deliberately not clever: this does **not** see through `opc.tcp://localhost:48050`
 * versus `opc.tcp://127.0.0.1:48050`, which are the same server spelled two ways. Seeing
 * through it means resolving hostnames, which the browser cannot do and the server should
 * not do inside a request handler. Exact-string is right for the case that occurs — a
 * VirtualPEA plant, where only the port differs.
 */
export function normaliseEndpoint(url: string): string {
  return url.trim().replace(/\/+$/, '').toLowerCase()
}

/**
 * The normalised endpoints used by **more than one** PEA in the list.
 *
 * Scoped to whatever list it is given, which is one project's PEAs — the same boundary the
 * server uses, and for the same reason: a recipe binds its steps within one project, so
 * that is where a collision does damage. The same physical module legitimately appears in
 * two different plant configurations.
 *
 * Empty endpoints are ignored rather than grouped: an MTP that declares no OPC UA server
 * stores `""`, and several of those are not "the same endpoint", they are several unknowns.
 */
export function conflictingEndpoints(peas: readonly PeaSummary[]): Set<string> {
  const seen = new Map<string, number>()
  for (const pea of peas) {
    const key = normaliseEndpoint(pea.endpoint_url)
    if (key) seen.set(key, (seen.get(key) ?? 0) + 1)
  }
  return new Set([...seen].filter(([, count]) => count > 1).map(([key]) => key))
}

/** Whether this PEA shares its endpoint with another in the same list. */
export function hasEndpointConflict(conflicts: ReadonlySet<string>, endpointUrl: string): boolean {
  return conflicts.has(normaliseEndpoint(endpointUrl))
}
