// Wire types — mirror backend/orchestrion/api/schemas.py.

export interface Project {
  id: number
  name: string
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

export interface Procedure {
  name: string
  procedure_id: number
  is_self_completing: boolean
}

export interface Service {
  name: string
  procedures: Procedure[]
  control_nodes: NodeInfo[]
}

export interface PeaDetail extends PeaSummary {
  type_name: string
  mtp_version: string
  device_revision: string
  manufacturer_uri: string
  product_code: string
  services: Service[]
}

// Live-state messages over the WebSocket (backend/orchestrion/api/live.py).
export type LiveMessage =
  | {
      type: 'snapshot'
      connected: boolean
      states: Record<string, string>
      command_en: Record<string, string[]>
    }
  | { type: 'update'; service: string; state?: string; command_en?: string[] }
  | { type: 'error'; detail: string }
