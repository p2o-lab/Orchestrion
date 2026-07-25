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
