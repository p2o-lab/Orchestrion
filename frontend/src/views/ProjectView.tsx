import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PeaSummary, RecipeSummary } from '../api/types'
import { useWorkspace } from '../workspace'
import { Button, Card, Input, Modal, Spinner } from '../ui/primitives'
import { Icon } from '../ui/icons'
import { ConfirmDialog } from '../ui/ConfirmDialog'
import { conflictingEndpoints, hasEndpointConflict } from '../ui/endpoints'
import { ImportDialog } from './ImportDialog'

interface LiveInfo {
  connected: boolean
  state?: string
}

export function ProjectView() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { projects, reload } = useWorkspace()
  const project = projects.find((p) => p.id === id)

  const [tab, setTab] = useState<'equipment' | 'recipes'>('equipment')
  const [peas, setPeas] = useState<PeaSummary[] | null>(null)
  const [recipes, setRecipes] = useState<RecipeSummary[] | null>(null)
  const [liveByPea, setLiveByPea] = useState<Record<number, LiveInfo>>({})
  const [importing, setImporting] = useState(false)
  const [creatingRecipe, setCreatingRecipe] = useState(false)
  const [editing, setEditing] = useState(false)
  const [renamingPea, setRenamingPea] = useState<PeaSummary | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftDesc, setDraftDesc] = useState('')
  const [confirming, setConfirming] = useState<{
    title: string
    message: string
    onConfirm: () => Promise<void>
  } | null>(null)

  const loadPeas = useCallback(async () => {
    const list = await api.listPeas(id)
    setPeas(list)
    // Reflect each PEA's real backend connection state on its card (dot colour).
    const entries = await Promise.all(
      list.map(async (p) => {
        try {
          const s = await api.liveStatus(p.id)
          const state = Object.values(s.states)[0]
          return [p.id, { connected: s.connected, state }] as const
        } catch {
          return [p.id, { connected: false }] as const
        }
      }),
    )
    setLiveByPea(Object.fromEntries(entries))
  }, [id])

  const loadRecipes = useCallback(async () => {
    setRecipes(await api.listRecipes(id))
  }, [id])

  /** Endpoints used by more than one PEA in this project — two rows, one physical server.
   *
   *  The import dialog warns at the moment it happens; this is the half that **persists**,
   *  because the conflict does. Import, look away, come back tomorrow and the plant would
   *  otherwise look fine. Free to compute: the list already carries every `endpoint_url`,
   *  so there is no extra request. The rule itself lives in `ui/endpoints.ts`, pure and
   *  tested, because it mirrors a server rule and mirrored rules drift. */
  const conflicts = useMemo(() => conflictingEndpoints(peas ?? []), [peas])

  useEffect(() => {
    setPeas(null)
    setRecipes(null)
    setLiveByPea({})
    loadPeas().catch(() => setPeas([]))
  }, [loadPeas])

  // Recipes load lazily the first time their tab is opened.
  useEffect(() => {
    if (tab === 'recipes' && recipes === null) loadRecipes().catch(() => setRecipes([]))
  }, [tab, recipes, loadRecipes])

  async function createRecipe() {
    const name = draftName.trim()
    if (!name) return
    await api.createRecipe(id, {
      header: { name, version: 1, author: '', product: '' },
      formula: {},
      steps: [],
      transitions: [],
    })
    setCreatingRecipe(false)
    await loadRecipes()
  }

  function deleteRecipe(recipe: RecipeSummary) {
    setConfirming({
      title: 'Delete recipe',
      message: `"${recipe.name}" will be permanently removed.`,
      onConfirm: async () => {
        await api.deleteRecipe(id, recipe.id)
        await loadRecipes()
        setConfirming(null)
      },
    })
  }

  async function afterImport() {
    await loadPeas()
    await reload()
  }

  function deleteProject() {
    setConfirming({
      title: 'Delete project',
      message: `"${project?.name}" and all of its PEAs will be permanently removed.`,
      onConfirm: async () => {
        await api.deleteProject(id)
        await reload()
        navigate('/')
      },
    })
  }

  function deletePea(pea: PeaSummary) {
    setConfirming({
      title: 'Delete PEA',
      message: `"${pea.name}" will be permanently removed from this project.`,
      onConfirm: async () => {
        await api.deletePea(pea.id)
        await afterImport()
        setConfirming(null)
      },
    })
  }

  async function saveProject() {
    if (!draftName.trim()) return
    await api.updateProject(id, { name: draftName.trim(), description: draftDesc.trim() })
    await reload()
    setEditing(false)
  }

  async function renamePea() {
    if (!renamingPea || !draftName.trim()) return
    await api.renamePea(renamingPea.id, draftName.trim())
    setRenamingPea(null)
    await loadPeas()
  }

  return (
    <div className="w-full px-10 py-9">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4 animate-fade-in">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-xs text-faint">
            <Link to="/" className="transition hover:text-dim">Workspace</Link>
            <Icon name="chevron" size={13} />
            <span>Project</span>
          </div>
          <h1 className="text-2xl text-ink">{project?.name ?? '…'}</h1>
          {project?.description ? (
            <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-dim">{project.description}</p>
          ) : (
            <button
              onClick={() => { setDraftName(project?.name ?? ''); setDraftDesc(''); setEditing(true) }}
              className="mt-1.5 text-sm text-faint transition hover:text-dim"
            >
              + Add a description
            </button>
          )}
          <p className="mt-2 text-xs text-faint">
            {tab === 'equipment'
              ? `${peas?.length ?? 0} equipment module${peas?.length === 1 ? '' : 's'}`
              : `${recipes?.length ?? 0} recipe${recipes?.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" small onClick={() => { setDraftName(project?.name ?? ''); setDraftDesc(project?.description ?? ''); setEditing(true) }}>
            <Icon name="pencil" size={15} /> Edit
          </Button>
          <Button variant="danger" small onClick={deleteProject}>
            <Icon name="trash" size={15} /> Delete
          </Button>
          {tab === 'equipment' ? (
            <Button variant="primary" onClick={() => setImporting(true)}>
              <Icon name="plus" size={16} /> Import PEA
            </Button>
          ) : (
            <Button variant="primary" onClick={() => { setDraftName(''); setCreatingRecipe(true) }}>
              <Icon name="plus" size={16} /> New recipe
            </Button>
          )}
        </div>
      </div>

      {/* tabs */}
      <div className="mt-6 flex items-center gap-6 border-b border-edge">
        {(['equipment', 'recipes'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-1 pb-3 text-sm transition ${
              tab === t
                ? 'border-accent font-medium text-ink'
                : 'border-transparent text-faint hover:text-dim'
            }`}
          >
            <Icon name={t === 'equipment' ? 'module' : 'recipe'} size={16} />
            {t === 'equipment' ? 'Equipment' : 'Recipes'}
          </button>
        ))}
      </div>

      {/* PEA grid (Equipment tab) */}
      {tab === 'equipment' && (peas === null ? (
        <div className="grid place-items-center py-24"><Spinner className="h-6 w-6" /></div>
      ) : peas.length === 0 ? (
        <Card className="mt-8 flex flex-col items-center gap-4 p-14 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-accent/12 text-accent">
            <Icon name="module" size={26} />
          </span>
          <p className="text-dim">No PEAs imported yet.</p>
          <Button variant="primary" onClick={() => setImporting(true)}>
            <Icon name="plus" size={16} /> Import your first PEA
          </Button>
        </Card>
      ) : (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {peas.map((pea, i) => {
            const info = liveByPea[pea.id] ?? { connected: false }
            return (
              <div key={pea.id} className="animate-rise" style={{ animationDelay: `${i * 45}ms` }}>
                <Card className="edge-top-accent group relative overflow-hidden p-5 transition duration-200 hover:-translate-y-1 hover:border-accent/40 hover:shadow-[0_20px_50px_-12px_rgba(0,0,0,0.6)]">
                  {/* hover actions (top-right) — no longer collide with the state dot */}
                  <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition group-hover:opacity-100">
                    <button
                      onClick={() => { setRenamingPea(pea); setDraftName(pea.name) }}
                      className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-white/8 hover:text-accent"
                      title="Rename PEA"
                    >
                      <Icon name="pencil" size={15} />
                    </button>
                    <button
                      onClick={() => deletePea(pea)}
                      className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-white/8 hover:text-danger"
                      title="Delete PEA"
                    >
                      <Icon name="trash" size={15} />
                    </button>
                  </div>

                  <Link to={`/projects/${id}/peas/${pea.id}`} className="block">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/12 text-accent transition group-hover:bg-accent/20">
                      <Icon name="module" size={20} />
                    </span>
                    <div className="mt-4 flex items-center gap-2">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${
                          info.connected
                            ? 'bg-st-execute shadow-[0_0_8px_1px] shadow-st-execute pulse-dot'
                            : 'bg-st-stopped'
                        }`}
                        title={info.connected ? `connected · ${info.state ?? 'live'}` : 'disconnected'}
                      />
                      <span className="truncate text-base font-semibold text-ink">{pea.name}</span>
                    </div>
                    <div className="mt-2 truncate font-mono text-xs text-dim">{pea.endpoint_url || '—'}</div>
                    {hasEndpointConflict(conflicts, pea.endpoint_url) && (
                      <div
                        className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn"
                        title={`Another PEA in this project uses ${pea.endpoint_url}. Both talk to the same server, so a recipe using both will fail when the second step finds the service already running.`}
                      >
                        ⚠ shared endpoint
                      </div>
                    )}
                    <div className="mt-1 truncate text-xs text-faint">{pea.aml_filename}</div>
                    <div className="mt-4 flex items-center gap-1 text-xs font-medium text-accent opacity-0 transition group-hover:opacity-100">
                      Open control view <Icon name="chevron" size={14} />
                    </div>
                  </Link>
                </Card>
              </div>
            )
          })}
        </div>
      ))}

      {/* Recipes tab */}
      {tab === 'recipes' && (recipes === null ? (
        <div className="grid place-items-center py-24"><Spinner className="h-6 w-6" /></div>
      ) : recipes.length === 0 ? (
        <Card className="mt-8 flex flex-col items-center gap-4 p-14 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-accent/12 text-accent">
            <Icon name="recipe" size={26} />
          </span>
          <p className="text-dim">No recipes yet.</p>
          <p className="max-w-sm text-xs leading-relaxed text-faint">
            A recipe sequences this project's PEA services into one orchestrated run.
          </p>
          <Button variant="primary" onClick={() => { setDraftName(''); setCreatingRecipe(true) }}>
            <Icon name="plus" size={16} /> New recipe
          </Button>
        </Card>
      ) : (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {recipes.map((recipe, i) => (
            <div key={recipe.id} className="animate-rise" style={{ animationDelay: `${i * 45}ms` }}>
              <Card className="edge-top-accent group relative overflow-hidden p-5 transition duration-200 hover:-translate-y-1 hover:border-accent/40 hover:shadow-[0_20px_50px_-12px_rgba(0,0,0,0.6)]">
                <div className="absolute right-3 top-3 opacity-0 transition group-hover:opacity-100">
                  <button
                    onClick={() => deleteRecipe(recipe)}
                    className="grid h-7 w-7 place-items-center rounded-md text-faint transition hover:bg-white/8 hover:text-danger"
                    title="Delete recipe"
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
                <Link to={`/projects/${id}/recipes/${recipe.id}`} className="block">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/12 text-accent transition group-hover:bg-accent/20">
                    <Icon name="recipe" size={20} />
                  </span>
                  <div className="mt-4 truncate text-base font-semibold text-ink">{recipe.name}</div>
                  <div className="mt-2 text-xs text-faint">
                    {recipe.step_count} step{recipe.step_count === 1 ? '' : 's'} · v{recipe.version}
                  </div>
                  <div className="mt-4 flex items-center gap-1 text-xs font-medium text-accent opacity-0 transition group-hover:opacity-100">
                    Open builder <Icon name="chevron" size={14} />
                  </div>
                </Link>
              </Card>
            </div>
          ))}
        </div>
      ))}

      {importing && (
        <ImportDialog projectId={id} onClose={() => setImporting(false)} onImported={afterImport} />
      )}

      {editing && (
        <Modal title="Edit project" onClose={() => setEditing(false)}>
          <label className="mb-1.5 block text-xs font-medium text-dim">Name</label>
          <Input autoFocus value={draftName} onChange={(e) => setDraftName(e.target.value)} />
          <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">Description</label>
          <textarea
            className="w-full resize-none rounded-lg border border-edge-strong bg-elev px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/20"
            rows={3}
            placeholder="What this plant configuration is for…"
            value={draftDesc}
            onChange={(e) => setDraftDesc(e.target.value)}
          />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="primary" onClick={saveProject} disabled={!draftName.trim()}>Save</Button>
          </div>
        </Modal>
      )}

      {confirming && (
        <ConfirmDialog
          title={confirming.title}
          message={confirming.message}
          onConfirm={confirming.onConfirm}
          onClose={() => setConfirming(null)}
        />
      )}

      {renamingPea && (
        <Modal title="Rename PEA" onClose={() => setRenamingPea(null)}>
          <Input autoFocus value={draftName} onChange={(e) => setDraftName(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && renamePea()} />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRenamingPea(null)}>Cancel</Button>
            <Button variant="primary" onClick={renamePea} disabled={!draftName.trim()}>Save</Button>
          </div>
        </Modal>
      )}

      {creatingRecipe && (
        <Modal title="New recipe" onClose={() => setCreatingRecipe(false)}>
          <label className="mb-1.5 block text-xs font-medium text-dim">Name</label>
          <Input
            autoFocus
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && createRecipe()}
            placeholder="e.g. Batch-42"
          />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreatingRecipe(false)}>Cancel</Button>
            <Button variant="primary" onClick={createRecipe} disabled={!draftName.trim()}>Create</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
