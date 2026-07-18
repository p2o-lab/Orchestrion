// Shared workspace state: the list of projects, so the sidebar and the views stay
// in sync after create/rename/delete/import (which changes a project's pea_count).

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api/client'
import type { Project } from './api/types'

interface WorkspaceCtx {
  projects: Project[]
  loading: boolean
  reload: () => Promise<void>
}

const Ctx = createContext<WorkspaceCtx | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    const list = await api.listProjects()
    setProjects(list)
    setLoading(false)
  }, [])

  useEffect(() => {
    reload().catch(() => setLoading(false))
  }, [reload])

  return <Ctx.Provider value={{ projects, loading, reload }}>{children}</Ctx.Provider>
}

export function useWorkspace(): WorkspaceCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return ctx
}
