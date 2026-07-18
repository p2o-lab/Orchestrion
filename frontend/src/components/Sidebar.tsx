import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useWorkspace } from '../workspace'
import { Button, Input, Modal } from '../ui/primitives'
import { Icon } from '../ui/icons'
import { Logo } from '../ui/Logo'

export function Sidebar() {
  const { projects, reload } = useWorkspace()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('sidebar-collapsed') === '1',
  )
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)

  function toggle() {
    setCollapsed((v) => {
      localStorage.setItem('sidebar-collapsed', v ? '0' : '1')
      return !v
    })
  }

  async function create() {
    if (!name.trim()) return
    setBusy(true)
    try {
      const project = await api.createProject(name.trim(), description.trim())
      await reload()
      setCreating(false)
      setName('')
      setDescription('')
      navigate(`/projects/${project.id}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-edge bg-elev/70 backdrop-blur-xl transition-[width] duration-200 ${
        collapsed ? 'w-[74px]' : 'w-64'
      }`}
    >
      {/* logo + collapse toggle (top) */}
      <div className={`flex py-4 ${collapsed ? 'flex-col items-center gap-3 px-0' : 'items-center justify-between px-5'}`}>
        <NavLink to="/" className="flex items-center gap-2.5">
          <Logo size={34} className="shrink-0 text-accent" />
          {!collapsed && <span className="text-[17px] font-semibold tracking-tight text-ink">Orchestrion</span>}
        </NavLink>
        <button
          onClick={toggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-white/8 hover:text-ink"
        >
          <Icon name="chevron" size={16} className={`transition ${collapsed ? '' : 'rotate-180'}`} />
        </button>
      </div>

      <div className="mx-4 h-px bg-edge" />

      {/* projects header / add */}
      <div className={`flex items-center pb-2 pt-4 ${collapsed ? 'justify-center px-0' : 'justify-between px-5'}`}>
        {!collapsed && (
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">Projects</span>
        )}
        <button
          onClick={() => setCreating(true)}
          className="grid h-7 w-7 place-items-center rounded-md text-dim transition hover:bg-white/8 hover:text-ink"
          title="New project"
        >
          <Icon name="plus" size={16} />
        </button>
      </div>

      <nav className={`flex-1 space-y-0.5 overflow-auto ${collapsed ? 'px-2.5' : 'px-3'}`}>
        {projects.map((p) => (
          <NavLink
            key={p.id}
            to={`/projects/${p.id}`}
            title={p.name}
            className={({ isActive }) =>
              'group relative flex items-center rounded-lg py-2 text-sm transition ' +
              (collapsed ? 'justify-center px-0' : 'gap-2.5 px-3') +
              (isActive ? ' bg-accent/12 text-ink' : ' text-dim hover:bg-white/6 hover:text-ink')
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent" />
                )}
                <Icon name="folder" size={16} className={isActive ? 'text-accent' : 'text-faint group-hover:text-dim'} />
                {!collapsed && (
                  <>
                    <span className="flex-1 truncate">{p.name}</span>
                    <span className="shrink-0 rounded-md bg-white/8 px-1.5 py-0.5 text-[11px] text-faint">
                      {p.pea_count}
                    </span>
                  </>
                )}
              </>
            )}
          </NavLink>
        ))}
        {projects.length === 0 && !collapsed && (
          <button
            onClick={() => setCreating(true)}
            className="mt-1 w-full rounded-lg border border-dashed border-edge-strong px-3 py-3 text-left text-sm text-faint transition hover:border-accent/50 hover:text-dim"
          >
            + Create your first project
          </button>
        )}
      </nav>

      {/* footer */}
      {!collapsed && (
        <div className="border-t border-edge px-5 py-4 text-[11px] leading-relaxed text-faint">
          <span className="font-medium text-dim">Process Orchestration Layer</span>
          <br />MTP 1.1.0 · CAEX 3.0
        </div>
      )}

      {creating && (
        <Modal title="New project" onClose={() => setCreating(false)}>
          <label className="mb-1.5 block text-xs font-medium text-dim">Name</label>
          <Input
            autoFocus
            placeholder="e.g. Reactor Line A"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && create()}
          />
          <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">
            Description <span className="text-faint">(optional)</span>
          </label>
          <textarea
            className="w-full resize-none rounded-lg border border-edge-strong bg-elev px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/20"
            rows={3}
            placeholder="What this plant configuration is for…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" onClick={create} disabled={busy || !name.trim()}>
              Create project
            </Button>
          </div>
        </Modal>
      )}
    </aside>
  )
}
