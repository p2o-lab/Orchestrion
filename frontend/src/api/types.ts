// Wire types — mirror backend/orchestrion/api/schemas.py.

export interface Project {
  id: number
  name: string
  description: string
  created_at: string
  pea_count: number
}

export interface PeaSummary {
  id: number
  project_id: number
  name: string
  aml_filename: string
  endpoint_url: string
  created_at: string
}

/** The import response — mirrors `schemas.py::PeaImported`.
 *
 *  A `PeaSummary` that may carry a **non-blocking** warning: the import succeeded, but
 *  there is something the operator should know. Today the only case is another PEA in the
 *  same project already on this OPC UA endpoint, which means two modules talking to one
 *  server. Only this response has the field — list and rename return a plain `PeaSummary`. */
export interface PeaImported extends PeaSummary {
  warning: string | null
}

export interface NodeInfo {
  name: string
  namespace: string
  identifier: string
  identifier_type: string
  access: string
}

export interface Parameter {
  name: string
  kind: string // 'analog' | 'integer' | 'binary' | 'string'
}

// A value's static descriptor — mirrors ValueSchema. The live number arrives on the
// WebSocket keyed by `name`; this says what kind it is and which way it flows.
export interface ValueDescriptor {
  name: string
  kind: string // 'analog' | 'integer' | 'binary' | 'string'
  direction: 'in' | 'out'
  writable: boolean
}

// A live value's current reading (number for analog/integer, boolean for binary).
export type LiveValue = number | boolean | string

// Scaling + unit for an analog value, read once at connect ([2658-3] §7.5/§7.6).
// `unit` is the Table 10 code; the UI maps it to a symbol.
export interface ValueMeta {
  unit?: number
  scl_min?: number
  scl_max?: number
}

export interface Procedure {
  name: string
  procedure_id: number
  is_self_completing: boolean
  parameters: Parameter[]
  report_values: ValueDescriptor[]
  process_values: ValueDescriptor[]
}

export interface Service {
  name: string
  procedures: Procedure[]
  config_parameters: ValueDescriptor[]
  control_nodes: NodeInfo[]
}

export interface PeaDetail extends PeaSummary {
  type_name: string
  mtp_version: string
  device_revision: string
  manufacturer_uri: string
  product_code: string
  services: Service[]
  process_values: ValueDescriptor[]
}

// One event-log entry (M4) — mirrors orchestrion/events.py Event.to_dict().
export interface LogEvent {
  timestamp: string // ISO 8601, UTC
  kind: string // 'state_transition' | 'command' | 'connection' | 'value_write'
  message: string
  detail: string | null
}

// ── Recipes (v0.2.0) — mirror orchestrion/recipe/model.py + api/recipes.py ──────────

/** The step completing is the only gate — drawn `=1` in GRAFCET.
 *  Not valid on a transition with a *continuous* step before it: there the receptivity IS the
 *  completion criterion, so this would complete the service the instant it started. The
 *  backend rejects that (422); `recipeGraph.defaultCondition` never offers it. */
export interface Always { type: 'Always' }
export interface StateReached { type: 'StateReached'; pea_id: number; service: string; state: string }
export interface ValueThreshold {
  type: 'ValueThreshold'
  pea_id: number
  value_name: string
  op: '<' | '<=' | '>' | '>=' | '==' | '!='
  threshold: number
}
export interface Elapsed { type: 'Elapsed'; seconds: number }
export interface AndCond { type: 'And'; conditions: Condition[] }
export interface OrCond { type: 'Or'; conditions: Condition[] }
export type Condition = Always | StateReached | ValueThreshold | Elapsed | AndCond | OrCond

export interface RecipeStep {
  id: string
  pea_id: number
  service: string
  procedure_id: number
  params: Record<string, number>
  x?: number | null // UI-only canvas position (non-normative); mirrors the backend model
  y?: number | null
}

export interface Transition {
  from_ids: string[]
  to_ids: string[] // may contain the "END" sentinel
  condition: Condition
}

export interface RecipeHeader { name: string; version: number; author: string; product: string }

export interface MasterRecipe {
  header: RecipeHeader
  formula: Record<string, number>
  steps: RecipeStep[]
  transitions: Transition[]
}

export interface RecipeSummary {
  id: number
  project_id: number
  name: string
  version: number
  step_count: number
  created_at: string
}

export interface RecipeDetail extends RecipeSummary {
  definition: MasterRecipe
}

// ── Runs (M5.5) — mirror `recipe/runs.py::RunRecord.to_dict()` ──────────────────────

/** A run's status. **Observed, not commanded** (step model §10): `held`/`paused` are derived
 *  each pass from the steps' live states and clear again by themselves when the operator
 *  resumes the service. Only the three terminal values are set once and final. */
export type RunStatus = 'running' | 'held' | 'paused' | 'completed' | 'failed' | 'aborted'

/** Where one step is in its lifecycle — `POL_Step_Model_ISA88.md` §8, and the engine's
 *  `StepState`. Four, not two:
 *  - `running`     — the service is in an acting state ([IEC 61512-1] item 2382);
 *  - `completing`  — *continuous only*: the receptivity fired, `COMPLETE` was sent, and the
 *                    engine is awaiting the final state;
 *  - `terminated`  — a Final State was reached and **latched**; gate 1 is satisfied and the
 *                    step is waiting on its transition's receptivity (gate 2). This is the
 *                    state that makes *"S1 finished, waiting for Temp > 80"* observable;
 *  - `done`        — the transition fired; the step is settled and its service was `RESET`. */
export type StepState = 'running' | 'completing' | 'terminated' | 'done'

export interface RunEvent {
  timestamp: string // ISO 8601, UTC
  message: string
}

export interface RunReport {
  run_id: number
  project_id: number
  recipe_id: number
  recipe_name: string
  status: RunStatus
  error: string | null
  /** Only steps that have been **activated** appear; one not yet reached is absent. */
  steps: Record<string, StepState>
  /** **The latch** (step model §5) — which Final State each terminated step reached, as a
   *  [2658-4 Table 14] `ServiceState` name, recorded at the instant it was observed. */
  terminal: Record<string, string>
  /** Which steps are `HELD` or `PAUSED` **right now** (step model §7 levels 1-2).
   *
   *  `status` says the run is held; this says *where*. It cannot be derived from `steps`,
   *  because an interrupted step stays `running` there — HELD is neither acting nor final,
   *  so the engine's `_observe` falls through. Recomputed every pass, so it clears itself
   *  when the operator releases the service. */
  interrupted: Record<string, string>
  started_at: string
  finished_at: string | null
  events: RunEvent[]
}

/** What `POST …/run` and `POST …/abort` return. */
export interface RunHandle {
  run_id: number
  status: RunStatus
}

// Live-state messages over the WebSocket (backend/orchestrion/api/live.py).
export type LiveMessage =
  | {
      type: 'snapshot'
      connected: boolean
      states: Record<string, string>
      command_en: Record<string, string[]>
      values: Record<string, LiveValue>
      value_meta: Record<string, ValueMeta>
    }
  | { type: 'update'; service: string; state?: string; command_en?: string[] }
  | { type: 'update'; name: string; value: LiveValue }
  | { type: 'log_snapshot'; events: LogEvent[] }
  | ({ type: 'log' } & LogEvent)
  | { type: 'error'; detail: string }
