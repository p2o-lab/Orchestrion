import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PeaSummary } from '../api/types'
import { useWorkspace } from '../workspace'
import { Button, Card, Input, Modal, Spinner } from '../ui/primitives'
import { ImportDialog } from './ImportDialog'

export function ProjectView() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { projects, reload } = useWorkspace()
  const project = projects.find((p) => p.id === id)

  const [peas, setPeas] = useState<PeaSummary[] | null>(null)
  const [importing, setImporting] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState('')

  const loadPeas = useCallback(async () => {
    setPeas(await api.listPeas(id))
  }, [id])

  useEffect(() => {
    setPeas(null)
    loadPeas().catch(() => setPeas([]))
  }, [loadPeas])

  async function afterImport() {
    await loadPeas()
    await reload() // pea_count in the sidebar
  }

  async function deleteProject() {
    if (!confirm(`Delete project "${project?.name}" and all its PEAs?`)) return
    await api.deleteProject(id)
    await reload()
    navigate('/')
  }

  async function deletePea(pea: PeaSummary) {
    if (!confirm(`Delete PEA "${pea.name}"?`)) return
    await api.deletePea(pea.id)
    await afterImport()
  }

  async function renameProject() {
    if (!newName.trim()) return
    await api.renameProject(id, newName.trim())
    await reload()
    setRenaming(false)
  }

  return (
    <div className="mx-auto max-w-6xl px-10 py-9">
      {/* header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl text-ink">{project?.name ?? '…'}</h1>
          <p className="mt-1 text-sm text-faint">Plant configuration · {peas?.length ?? 0} equipment modules</p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" small onClick={() => { setNewName(project?.name ?? ''); setRenaming(true) }}>
            Rename
          </Button>
          <Button variant="danger" small onClick={deleteProject}>Delete</Button>
          <Button variant="primary" onClick={() => setImporting(true)}>+ Import PEA</Button>
        </div>
      </div>

      {/* tabs (roadmap) */}
      <div className="mt-6 flex items-center gap-6 border-b border-edge">
        <span className="-mb-px border-b-2 border-accent pb-2.5 text-sm font-medium text-ink">Equipment</span>
        <span className="pb-2.5 text-sm text-faint" title="Coming later">Recipes · soon</span>
      </div>

      {/* PEA grid */}
      {peas === null ? (
        <div className="grid place-items-center py-24"><Spinner className="h-6 w-6" /></div>
      ) : peas.length === 0 ? (
        <Card className="mt-8 p-10 text-center">
          <p className="text-dim">No PEAs imported yet.</p>
          <div className="mt-4 flex justify-center">
            <Button variant="primary" onClick={() => setImporting(true)}>+ Import your first PEA</Button>
          </div>
        </Card>
      ) : (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {peas.map((pea) => (
            <Card key={pea.id} className="group relative p-5 transition hover:border-accent/40">
              <Link to={`/projects/${id}/peas/${pea.id}`} className="block">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-st-stopped" />
                  <span className="truncate text-base font-semibold text-ink">{pea.name}</span>
                </div>
                <div className="mt-3 space-y-1.5 text-xs">
                  <div className="truncate font-mono text-dim">{pea.endpoint_url || '—'}</div>
                  <div className="truncate text-faint">{pea.aml_filename}</div>
                </div>
                <div className="mt-4 text-xs font-medium text-accent opacity-0 transition group-hover:opacity-100">
                  Open control view →
                </div>
              </Link>
              <button
                onClick={() => deletePea(pea)}
                className="absolute right-3 top-3 hidden rounded-md px-2 py-1 text-xs text-faint transition hover:bg-white/5 hover:text-danger group-hover:block"
                title="Delete PEA"
              >
                ✕
              </button>
            </Card>
          ))}
        </div>
      )}

      {importing && (
        <ImportDialog projectId={id} onClose={() => setImporting(false)} onImported={afterImport} />
      )}
      {renaming && (
        <Modal title="Rename project" onClose={() => setRenaming(false)}>
          <Input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && renameProject()} />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRenaming(false)}>Cancel</Button>
            <Button variant="primary" onClick={renameProject} disabled={!newName.trim()}>Save</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
