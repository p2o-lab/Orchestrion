import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useWorkspace } from '../workspace'
import { Button, Input, Modal } from '../ui/primitives'

export function Sidebar() {
  const { projects, reload } = useWorkspace()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function create() {
    if (!name.trim()) return
    setBusy(true)
    try {
      const project = await api.createProject(name.trim())
      await reload()
      setCreating(false)
      setName('')
      navigate(`/projects/${project.id}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-edge bg-elev/60">
      <NavLink to="/" className="flex items-center gap-2.5 px-5 py-5">
        <span className="h-7 w-7 rounded-lg bg-gradient-to-br from-accent-bright to-accent shadow-[0_3px_14px_rgba(124,156,255,0.4)]" />
        <span className="text-[17px] font-semibold tracking-tight text-ink">Orchestrion</span>
      </NavLink>

      <div className="flex items-center justify-between px-5 pt-2 pb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-faint">Projects</span>
        <button
          onClick={() => setCreating(true)}
          className="grid h-6 w-6 place-items-center rounded-md text-dim transition hover:bg-white/5 hover:text-ink"
          title="New project"
        >
          +
        </button>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-auto px-3">
        {projects.map((p) => (
          <NavLink
            key={p.id}
            to={`/projects/${p.id}`}
            className={({ isActive }) =>
              'flex items-center justify-between rounded-lg px-3 py-2 text-sm transition ' +
              (isActive ? 'bg-accent/12 text-ink' : 'text-dim hover:bg-white/5 hover:text-ink')
            }
          >
            <span className="truncate">{p.name}</span>
            <span className="ml-2 shrink-0 rounded-md bg-white/6 px-1.5 py-0.5 text-[11px] text-faint">
              {p.pea_count}
            </span>
          </NavLink>
        ))}
        {projects.length === 0 && (
          <p className="px-3 py-2 text-sm text-faint">No projects yet.</p>
        )}
      </nav>

      <div className="px-5 py-4 text-[11px] text-faint">
        Process Orchestration Layer · MTP 1.1.0
      </div>

      {creating && (
        <Modal title="New project" onClose={() => setCreating(false)}>
          <Input
            autoFocus
            placeholder="e.g. Reactor Line A"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && create()}
          />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" onClick={create} disabled={busy || !name.trim()}>
              Create
            </Button>
          </div>
        </Modal>
      )}
    </aside>
  )
}
