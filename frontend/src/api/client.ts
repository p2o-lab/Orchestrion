// Thin typed wrapper over the POL REST API. All calls go through the Vite proxy
// (/api -> 127.0.0.1:8000). A non-2xx throws ApiError carrying the parsed message,
// so the import flow can surface the parser's message inline.

import type { PeaDetail, PeaSummary, Project } from './types'

export class ApiError extends Error {
  readonly status: number
  readonly body?: unknown
  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

function messageFrom(body: any, res: Response): string {
  const detail = body?.detail
  if (detail && typeof detail === 'object' && typeof detail.detail === 'string') return detail.detail
  if (typeof detail === 'string') return detail
  return `${res.status} ${res.statusText}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => undefined)
    throw new ApiError(res.status, messageFrom(body, res), body)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  listProjects: () => request<Project[]>('/api/projects'),
  createProject: (name: string) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name }) }),
  renameProject: (id: number, name: string) =>
    request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  listPeas: (projectId: number) => request<PeaSummary[]>(`/api/projects/${projectId}/peas`),
  getPea: (peaId: number) => request<PeaDetail>(`/api/peas/${peaId}`),
  renamePea: (peaId: number, name: string) =>
    request<PeaSummary>(`/api/peas/${peaId}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deletePea: (peaId: number) => request<void>(`/api/peas/${peaId}`, { method: 'DELETE' }),

  // Multipart import; on 422 ApiError.message is the parser's clause-level message.
  async importPea(projectId: number, name: string, file: File): Promise<PeaSummary> {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    const res = await fetch(`/api/projects/${projectId}/peas`, { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => undefined)
      throw new ApiError(res.status, messageFrom(body, res), body)
    }
    return res.json() as Promise<PeaSummary>
  },
}
