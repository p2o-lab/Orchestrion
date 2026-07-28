import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api/client'
import type { Condition, MasterRecipe, PeaDetail, RecipeDetail, RecipeHeader, RecipeStep } from '../api/types'
import { graphToTransitions, recipeToGraph, END_ID, type GraphEdge, type GraphNode } from '../ui/recipeGraph'
import { Icon } from '../ui/icons'
import { Button, Modal, Spinner } from '../ui/primitives'
import { StepNode, type StepNodeData } from './StepNode'
import { EndNode } from './EndNode'
import { AndNode, OrNode } from './FlowNodes'
import { ConditionEditor } from './ConditionEditor'
import { StepEditor } from './StepEditor'
import { RecipeSettings } from './RecipeSettings'
import { NodePalette, DRAG_KEY, type PaletteKind } from './NodePalette'

const nodeTypes = { step: StepNode, end: EndNode, and: AndNode, or: OrNode }
const DEFAULT_COND: Condition = { type: 'StateReached', pea_id: 0, service: '', state: 'COMPLETED' }

const selectClass =
  'w-full rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

function nextStepId(ids: string[]): string {
  const used = new Set(ids)
  let n = 1
  while (used.has(`s${n}`)) n++
  return `s${n}`
}

function summarize(c: Condition): string {
  switch (c.type) {
    case 'StateReached': return `✓ ${c.state}`
    case 'ValueThreshold': return `${c.value_name} ${c.op} ${c.threshold}`
    case 'Elapsed': return `after ${c.seconds}s`
    case 'And': return 'ALL of…'
    case 'Or': return 'ANY of…'
  }
}

function edgeFor(source: string, target: string, condition: Condition, key: string): Edge {
  return { id: key, source, target, label: summarize(condition), data: { condition } }
}

// ── React Flow node/edge ⇄ the pure GraphNode/GraphEdge the mapping module speaks ──
function toGraphNode(n: Node): GraphNode {
  if (n.type === 'step') {
    const d = n.data as StepNodeData
    return { id: n.id, kind: 'step', pea_id: d.pea_id, service: d.service, procedure_id: d.procedure_id, params: d.params, x: n.position.x, y: n.position.y }
  }
  if (n.type === 'and') return { id: n.id, kind: 'and' }
  if (n.type === 'or') return { id: n.id, kind: 'or' }
  return { id: n.id, kind: 'end' }
}
function toGraphEdge(e: Edge): GraphEdge {
  return { source: e.source, target: e.target, condition: (e.data as { condition?: Condition } | undefined)?.condition }
}

export function RecipeBuilder() {
  const { projectId, recipeId } = useParams()
  const pid = Number(projectId)
  const rid = Number(recipeId)

  const [recipe, setRecipe] = useState<RecipeDetail | null>(null)
  const [peas, setPeas] = useState<PeaDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [adding, setAdding] = useState(false)
  const [editingEdge, setEditingEdge] = useState<Edge | null>(null)
  const [editingStep, setEditingStep] = useState<Node | null>(null)
  const [header, setHeader] = useState<RecipeHeader | null>(null)
  const [formula, setFormula] = useState<Record<string, number>>({})
  const [showSettings, setShowSettings] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [rf, setRf] = useState<ReactFlowInstance | null>(null)
  const [showMiniMap, setShowMiniMap] = useState(true)
  const stepDropPos = useRef<{ x: number; y: number } | null>(null)
  const seeded = useRef(false)

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

  const peaById = useCallback((id: number) => peas?.find((p) => p.id === id), [peas])
  const procedureName = useCallback(
    (peaId: number, service: string, procedureId: number) => {
      const svc = peaById(peaId)?.services.find((s) => s.name === service)
      return svc?.procedures.find((p) => p.procedure_id === procedureId)?.name ?? `#${procedureId}`
    },
    [peaById],
  )

  // Seed the canvas once recipe + PEAs are in — reconstructing fork/join from the transitions.
  useEffect(() => {
    if (seeded.current || !recipe || !peas) return
    seeded.current = true
    const g = recipeToGraph(recipe.definition)

    const pos: Record<string, { x: number; y: number }> = {}
    g.nodes.filter((n) => n.kind === 'step').forEach((n, i) => {
      pos[n.id] = { x: n.x ?? 80 + (i % 4) * 240, y: n.y ?? 80 + Math.floor(i / 4) * 170 }
    })
    pos[END_ID] = { x: 80 + 3 * 240, y: 380 }
    g.nodes.filter((n) => n.kind === 'and' || n.kind === 'or').forEach((n) => {
      const neigh = g.edges.filter((e) => e.source === n.id || e.target === n.id).map((e) => (e.source === n.id ? e.target : e.source))
      const pts = neigh.map((id) => pos[id]).filter(Boolean) as { x: number; y: number }[]
      pos[n.id] = pts.length
        ? { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length }
        : { x: 340, y: 200 }
    })

    const rfNodes: Node[] = g.nodes.map((n) => {
      if (n.kind === 'step')
        return {
          id: n.id, type: 'step', position: pos[n.id],
          data: {
            pea_id: n.pea_id!, service: n.service!, procedure_id: n.procedure_id!, params: n.params ?? {},
            pea: peaById(n.pea_id!)?.name ?? `PEA ${n.pea_id}`,
            procedure: procedureName(n.pea_id!, n.service!, n.procedure_id!),
          } satisfies StepNodeData,
        }
      if (n.kind === 'end') return { id: n.id, type: 'end', deletable: false, position: pos[n.id], data: {} }
      return { id: n.id, type: n.kind, position: pos[n.id], data: {} } // 'and' | 'or'
    })
    const rfEdges: Edge[] = g.edges.map((e, i) => {
      const key = `t${i}-${e.source}-${e.target}`
      return e.condition ? edgeFor(e.source, e.target, e.condition, key) : { id: key, source: e.source, target: e.target }
    })

    setHeader(recipe.definition.header)
    setFormula(recipe.definition.formula)
    setNodes(rfNodes)
    setEdges(rfEdges)
  }, [recipe, peas, peaById, procedureName, setNodes, setEdges])

  // Connect nodes. A plain step→(step|end) edge gets a default condition; edges touching a gateway
  // start bare — click the relevant one (the split's input / the merge's output / each OR branch)
  // to set its condition. graphToTransitions defaults any still-empty guard to "source ✓ COMPLETED".
  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target || c.source === c.target) return
      const srcNode = nodes.find((n) => n.id === c.source)
      const tgtNode = nodes.find((n) => n.id === c.target)
      const gate = (t?: string) => t === 'and' || t === 'or'
      const plain = srcNode?.type === 'step' && !gate(tgtNode?.type)
      setEdges((es) => {
        const key = `e-${c.source}-${c.target}-${Date.now()}`
        if (plain) {
          const d = srcNode!.data as StepNodeData
          const condition: Condition = { type: 'StateReached', pea_id: d.pea_id, service: d.service, state: 'COMPLETED' }
          return addEdge(edgeFor(c.source!, c.target!, condition, key), es)
        }
        return addEdge({ id: key, source: c.source!, target: c.target! }, es)
      })
      setSaved(false)
    },
    [nodes, setEdges],
  )

  function updateEdgeCondition(edgeId: string, condition: Condition) {
    setEdges((es) => es.map((e) => (e.id === edgeId ? { ...e, label: summarize(condition), data: { condition } } : e)))
    setSaved(false)
  }
  function updateStepParams(nodeId: string, params: Record<string, number>) {
    setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, params } } : n)))
    setSaved(false)
  }

  function addStep(peaId: number, service: string, procedureId: number) {
    const id = nextStepId(nodes.filter((n) => n.type === 'step').map((n) => n.id))
    const position = stepDropPos.current ?? { x: 180, y: 140 }
    stepDropPos.current = null
    setNodes((ns) => [
      ...ns,
      {
        id, type: 'step', position,
        data: {
          pea_id: peaId, service, procedure_id: procedureId, params: {},
          pea: peaById(peaId)?.name ?? `PEA ${peaId}`, procedure: procedureName(peaId, service, procedureId),
        } satisfies StepNodeData,
      },
    ])
    setSaved(false)
  }
  function addFlowNode(kind: 'and' | 'or', position = { x: 360, y: 180 }) {
    const id = `${kind}-${Date.now()}`
    setNodes((ns) => [...ns, { id, type: kind, position, data: {} }])
    setSaved(false)
  }

  // Palette: click drops in the middle; drag drops where released.
  function onQuickAdd(kind: PaletteKind) {
    if (kind === 'step') { stepDropPos.current = null; setAdding(true) }
    else addFlowNode(kind)
  }
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])
  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault()
      const kind = e.dataTransfer.getData(DRAG_KEY) as PaletteKind
      if (!kind || !rf) return
      const position = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      if (kind === 'step') { stepDropPos.current = position; setAdding(true) }
      else addFlowNode(kind, position)
    },
    [rf],
  )

  async function save() {
    if (!recipe) return
    setSaving(true)
    setError(null)
    try {
      const { transitions, error: mapErr } = graphToTransitions(nodes.map(toGraphNode), edges.map(toGraphEdge))
      if (mapErr) {
        setError(mapErr)
        setSaving(false)
        return
      }
      const steps: RecipeStep[] = nodes
        .filter((n) => n.type === 'step')
        .map((n) => {
          const d = n.data as StepNodeData
          return { id: n.id, pea_id: d.pea_id, service: d.service, procedure_id: d.procedure_id, params: d.params ?? {}, x: n.position.x, y: n.position.y }
        })
      const definition: MasterRecipe = { header: header ?? recipe.definition.header, formula, steps, transitions }
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
      <div className="flex items-center justify-between gap-4 border-b border-edge px-8 py-4">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-xs text-faint">
            <Link to="/" className="transition hover:text-dim">Workspace</Link>
            <Icon name="chevron" size={13} />
            <Link to={`/projects/${pid}`} className="transition hover:text-dim">Project</Link>
            <Icon name="chevron" size={13} />
            <span>Recipe</span>
          </div>
          <h1 className="truncate text-xl text-ink">{header?.name ?? recipe?.name ?? '…'}</h1>
        </div>
        <div className="flex items-center gap-2">
          {error && <span className="max-w-xs truncate text-xs text-danger" title={error}>{error}</span>}
          <Button variant="ghost" small onClick={() => setShowSettings(true)} disabled={!recipe}>
            <Icon name="pencil" size={15} /> Settings
          </Button>
          <Button variant="primary" small onClick={save} disabled={saving || !recipe}>
            {saving && <Spinner className="h-4 w-4" />}
            {saving ? 'Saving' : saved ? 'Saved ✓' : 'Save'}
          </Button>
        </div>
      </div>

      {recipe && peas && <NodePalette onQuickAdd={onQuickAdd} />}
      <div className="relative flex-1" onDrop={onDrop} onDragOver={onDragOver}>
        {recipe === null || peas === null ? (
          <div className="grid h-full place-items-center">
            {error ? <p className="text-sm text-danger">{error}</p> : <Spinner className="h-6 w-6" />}
          </div>
        ) : (
          <>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onInit={setRf}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onEdgeClick={(_, edge) => setEditingEdge(edge)}
                onNodeDoubleClick={(_, node) => { if (node.type === 'step') setEditingStep(node) }}
                nodeTypes={nodeTypes}
                colorMode="dark"
                fitView
                minZoom={0.2}
                deleteKeyCode={['Delete', 'Backspace']}
                onNodesDelete={() => setSaved(false)}
                onEdgesDelete={() => setSaved(false)}
                style={{ backgroundColor: '#171c27' }} // --color-canvas
              >
                <Background bgColor="#171c27" color="rgba(255,255,255,0.07)" gap={22} size={1} />
                <Controls />
                <Panel position="bottom-right" style={{ marginBottom: showMiniMap ? 158 : 8 }}>
                  <button
                    onClick={() => setShowMiniMap((v) => !v)}
                    className="rounded-md border border-edge bg-panel/80 px-2.5 py-1 text-xs text-dim backdrop-blur transition hover:text-ink"
                  >
                    {showMiniMap ? 'Hide map' : 'Show map'}
                  </button>
                </Panel>
                {showMiniMap && (
                  <MiniMap
                    pannable
                    zoomable
                    bgColor="#1c2330"
                    maskColor="rgba(20,25,36,0.7)"
                    nodeStrokeWidth={0}
                    nodeBorderRadius={4}
                    nodeColor={(n) => (n.type === 'or' ? '#fbbf24' : n.type === 'end' ? '#2dd4bf' : '#7c9cff')}
                    className="!overflow-hidden !rounded-lg !border !border-edge"
                  />
                )}
              </ReactFlow>
              {nodes.filter((n) => n.type === 'step').length === 0 && (
                <div className="pointer-events-none absolute inset-0 grid place-items-center">
                  <p className="text-sm text-faint">Drag a <span className="text-dim">Step</span> from the top onto the canvas.</p>
                </div>
              )}
            </>
          )}
        </div>

      {adding && peas && (
        <AddStepModal
          peas={peas}
          onClose={() => setAdding(false)}
          onAdd={(peaId, service, procedureId) => { addStep(peaId, service, procedureId); setAdding(false) }}
        />
      )}

      {editingEdge && peas && (
        <ConditionEditor
          peas={peas}
          initial={(editingEdge.data as { condition?: Condition }).condition ?? DEFAULT_COND}
          onClose={() => setEditingEdge(null)}
          onSave={(condition) => { updateEdgeCondition(editingEdge.id, condition); setEditingEdge(null) }}
        />
      )}

      {editingStep && peas && (
        <StepEditor
          pea={peas.find((p) => p.id === (editingStep.data as StepNodeData).pea_id)}
          data={editingStep.data as StepNodeData}
          onClose={() => setEditingStep(null)}
          onSave={(params) => { updateStepParams(editingStep.id, params); setEditingStep(null) }}
        />
      )}

      {showSettings && header && (
        <RecipeSettings
          header={header}
          formula={formula}
          onClose={() => setShowSettings(false)}
          onSave={(h, f) => { setHeader(h); setFormula(f); setSaved(false); setShowSettings(false) }}
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
      <select className={selectClass} value={peaId} onChange={(e) => { setPeaId(Number(e.target.value)); setService(''); setProcedureId('') }}>
        <option value="" disabled>Select a PEA…</option>
        {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>

      <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">Service</label>
      <select className={selectClass} value={service} disabled={peaId === ''} onChange={(e) => { setService(e.target.value); setProcedureId('') }}>
        <option value="" disabled>Select a service…</option>
        {services.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
      </select>

      <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">Procedure</label>
      <select className={selectClass} value={procedureId} disabled={service === ''} onChange={(e) => setProcedureId(Number(e.target.value))}>
        <option value="" disabled>Select a procedure…</option>
        {procedures.map((p) => (
          <option key={p.procedure_id} value={p.procedure_id}>
            {p.name}{p.is_self_completing ? ' · self-completing' : ' · continuous'}
          </option>
        ))}
      </select>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!ready} onClick={() => ready && onAdd(Number(peaId), service, Number(procedureId))}>
          Add step
        </Button>
      </div>
    </Modal>
  )
}
