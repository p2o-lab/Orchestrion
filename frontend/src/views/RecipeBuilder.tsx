import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api/client'
import type { MasterRecipe, PeaDetail, RecipeDetail, RecipeStep } from '../api/types'
import { Icon } from '../ui/icons'
import { Button, Modal, Spinner } from '../ui/primitives'
import { StepNode, type StepNodeData } from './StepNode'

const nodeTypes = { step: StepNode }

const selectClass =
  'w-full rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

// Smallest free "sN" id given the ids already in use.
function nextStepId(ids: string[]): string {
  const used = new Set(ids)
  let n = 1
  while (used.has(`s${n}`)) n++
  return `s${n}`
}

export function RecipeBuilder() {
  const { projectId, recipeId } = useParams()
  const pid = Number(projectId)
  const rid = Number(recipeId)

  const [recipe, setRecipe] = useState<RecipeDetail | null>(null)
  const [peas, setPeas] = useState<PeaDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges] = useEdgesState<Edge>([])
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const seeded = useRef(false)

  // Load the recipe and the project's PEAs (for the step picker + display names).
  useEffect(() => {
    seeded.current = false
    setRecipe(null)
    setPeas(null)
    setError(null)
    api.getRecipe(pid, rid).then(setRecipe).catch((e) => setError(String(e?.message ?? e)))
    api
      .listPeas(pid)
      .then((list) => Promise.all(list.map((p) => api.getPea(p.id))))
      .then(setPeas)
      .catch((e) => setError(String(e?.message ?? e)))
  }, [pid, rid])

  const peaById = useCallback(
    (id: number) => peas?.find((p) => p.id === id),
    [peas],
  )

  const procedureName = useCallback(
    (peaId: number, service: string, procedureId: number) => {
      const svc = peaById(peaId)?.services.find((s) => s.name === service)
      return svc?.procedures.find((p) => p.procedure_id === procedureId)?.name ?? `#${procedureId}`
    },
    [peaById],
  )

  // Seed the canvas once both the recipe and PEAs are in.
  useEffect(() => {
    if (seeded.current || !recipe || !peas) return
    seeded.current = true
    setNodes(
      recipe.definition.steps.map((s, i) => ({
        id: s.id,
        type: 'step',
        position: { x: s.x ?? 80 + (i % 4) * 240, y: s.y ?? 80 + Math.floor(i / 4) * 170 },
        data: {
          pea_id: s.pea_id,
          service: s.service,
          procedure_id: s.procedure_id,
          params: s.params,
          pea: peaById(s.pea_id)?.name ?? `PEA ${s.pea_id}`,
          procedure: procedureName(s.pea_id, s.service, s.procedure_id),
        } satisfies StepNodeData,
      })),
    )
    setEdges(
      recipe.definition.transitions.flatMap((t, ti) =>
        t.from_ids.flatMap((from) =>
          t.to_ids
            .filter((to) => to !== 'END')
            .map((to) => ({ id: `t${ti}-${from}-${to}`, source: from, target: to })),
        ),
      ),
    )
  }, [recipe, peas, peaById, procedureName, setNodes, setEdges])

  function addStep(peaId: number, service: string, procedureId: number) {
    const id = nextStepId(nodes.map((n) => n.id))
    const node: Node = {
      id,
      type: 'step',
      position: { x: 140, y: 120 + nodes.length * 18 },
      data: {
        pea_id: peaId,
        service,
        procedure_id: procedureId,
        params: {},
        pea: peaById(peaId)?.name ?? `PEA ${peaId}`,
        procedure: procedureName(peaId, service, procedureId),
      } satisfies StepNodeData,
    }
    setNodes((ns) => [...ns, node])
    setSaved(false)
  }

  async function save() {
    if (!recipe) return
    setSaving(true)
    try {
      const steps: RecipeStep[] = nodes.map((n) => {
        const d = n.data as StepNodeData
        return {
          id: n.id,
          pea_id: d.pea_id,
          service: d.service,
          procedure_id: d.procedure_id,
          params: d.params ?? {},
          x: n.position.x,
          y: n.position.y,
        }
      })
      const definition: MasterRecipe = {
        header: recipe.definition.header,
        formula: recipe.definition.formula,
        steps,
        transitions: recipe.definition.transitions, // transitions are edited in 2c
      }
      const summary = await api.updateRecipe(pid, rid, definition)
      setRecipe({ ...recipe, ...summary, definition })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <div className="flex items-center justify-between gap-4 border-b border-edge px-8 py-4">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-xs text-faint">
            <Link to="/" className="transition hover:text-dim">Workspace</Link>
            <Icon name="chevron" size={13} />
            <Link to={`/projects/${pid}`} className="transition hover:text-dim">Project</Link>
            <Icon name="chevron" size={13} />
            <span>Recipe</span>
          </div>
          <h1 className="truncate text-xl text-ink">{recipe?.name ?? '…'}</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" small onClick={() => setAdding(true)} disabled={!peas}>
            <Icon name="plus" size={15} /> Add step
          </Button>
          <Button variant="primary" small onClick={save} disabled={saving || !recipe}>
            {saving && <Spinner className="h-4 w-4" />}
            {saving ? 'Saving' : saved ? 'Saved ✓' : 'Save'}
          </Button>
        </div>
      </div>

      {/* canvas */}
      <div className="relative flex-1">
        {recipe === null || peas === null ? (
          <div className="grid h-full place-items-center">
            {error ? <p className="text-sm text-danger">{error}</p> : <Spinner className="h-6 w-6" />}
          </div>
        ) : (
          <>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              nodeTypes={nodeTypes}
              colorMode="dark"
              fitView
              minZoom={0.2}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center">
                <p className="text-sm text-faint">Empty recipe — add a step to begin.</p>
              </div>
            )}
          </>
        )}
      </div>

      {adding && peas && (
        <AddStepModal
          peas={peas}
          onClose={() => setAdding(false)}
          onAdd={(peaId, service, procedureId) => {
            addStep(peaId, service, procedureId)
            setAdding(false)
          }}
        />
      )}
    </div>
  )
}

function AddStepModal({
  peas,
  onAdd,
  onClose,
}: {
  peas: PeaDetail[]
  onAdd: (peaId: number, service: string, procedureId: number) => void
  onClose: () => void
}) {
  const [peaId, setPeaId] = useState<number | ''>('')
  const [service, setService] = useState('')
  const [procedureId, setProcedureId] = useState<number | ''>('')

  const pea = peas.find((p) => p.id === peaId)
  const services = pea?.services ?? []
  const procedures = services.find((s) => s.name === service)?.procedures ?? []
  const ready = peaId !== '' && service !== '' && procedureId !== ''

  return (
    <Modal title="Add step" onClose={onClose}>
      <label className="mb-1.5 block text-xs font-medium text-dim">PEA</label>
      <select
        className={selectClass}
        value={peaId}
        onChange={(e) => { setPeaId(Number(e.target.value)); setService(''); setProcedureId('') }}
      >
        <option value="" disabled>Select a PEA…</option>
        {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>

      <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">Service</label>
      <select
        className={selectClass}
        value={service}
        disabled={peaId === ''}
        onChange={(e) => { setService(e.target.value); setProcedureId('') }}
      >
        <option value="" disabled>Select a service…</option>
        {services.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
      </select>

      <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">Procedure</label>
      <select
        className={selectClass}
        value={procedureId}
        disabled={service === ''}
        onChange={(e) => setProcedureId(Number(e.target.value))}
      >
        <option value="" disabled>Select a procedure…</option>
        {procedures.map((p) => (
          <option key={p.procedure_id} value={p.procedure_id}>
            {p.name}{p.is_self_completing ? ' · self-completing' : ' · continuous'}
          </option>
        ))}
      </select>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!ready}
          onClick={() => ready && onAdd(Number(peaId), service, Number(procedureId))}
        >
          Add step
        </Button>
      </div>
    </Modal>
  )
}
