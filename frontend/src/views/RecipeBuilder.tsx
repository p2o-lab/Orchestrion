import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  addEdge,
  Background,
  Controls,
  MarkerType,
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
import { graphToTransitions, recipeToGraph, START_ID, END_ID, type GraphEdge, type GraphNode } from '../ui/recipeGraph'
import { Icon } from '../ui/icons'
import { Button, Modal, Spinner } from '../ui/primitives'
import { StepNode, type StepNodeData } from './StepNode'
import { EndNode } from './EndNode'
import { StartNode, TransitionNode, AndNode, OrNode, type TransitionNodeData } from './FlowNodes'
import { ConditionEditor } from './ConditionEditor'
import { StepEditor } from './StepEditor'
import { RecipeSettings } from './RecipeSettings'
import { NodePalette, DRAG_KEY, type PaletteKind } from './NodePalette'

const nodeTypes = { start: StartNode, step: StepNode, transition: TransitionNode, and: AndNode, or: OrNode, end: EndNode }
const DEFAULT_COND: Condition = { type: 'StateReached', pea_id: 0, service: '', state: 'COMPLETED' }

const selectClass =
  'w-full rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

// A plain directed GRAFCET link — just an arrow. The guard lives on the transition node, not here.
const EDGE: Partial<Edge> = { markerEnd: { type: MarkerType.ArrowClosed, color: '#7c9cff' }, style: { stroke: '#7c9cff', strokeWidth: 1.6 } }

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

const arrow = (source: string, target: string, key: string): Edge => ({ id: key, source, target, ...EDGE })

// ── React Flow node/edge ⇄ the pure GraphNode/GraphEdge the mapping module speaks ──
function toGraphNode(n: Node): GraphNode {
  if (n.type === 'step') {
    const d = n.data as StepNodeData
    return { id: n.id, kind: 'step', pea_id: d.pea_id, service: d.service, procedure_id: d.procedure_id, params: d.params, x: n.position.x, y: n.position.y }
  }
  if (n.type === 'transition') return { id: n.id, kind: 'transition', condition: (n.data as TransitionNodeData).condition }
  if (n.type === 'and') return { id: n.id, kind: 'and' }
  if (n.type === 'or') return { id: n.id, kind: 'or' }
  if (n.type === 'start') return { id: n.id, kind: 'start' }
  return { id: n.id, kind: 'end' }
}
const toGraphEdge = (e: Edge): GraphEdge => ({ source: e.source, target: e.target })

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
  const [editingTransition, setEditingTransition] = useState<Node | null>(null)
  const [editingStep, setEditingStep] = useState<Node | null>(null)
  const [header, setHeader] = useState<RecipeHeader | null>(null)
  const [formula, setFormula] = useState<Record<string, number>>({})
  const [showSettings, setShowSettings] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [rf, setRf] = useState<ReactFlowInstance | null>(null)
  const [showMiniMap, setShowMiniMap] = useState(true)
  const dropPos = useRef<{ x: number; y: number } | null>(null)
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

  // Seed the canvas once recipe + PEAs are in — GRAFCET graph from the transitions (§5.3.1).
  useEffect(() => {
    if (seeded.current || !recipe || !peas) return
    seeded.current = true
    const g = recipeToGraph(recipe.definition)

    // Position steps on a grid (honouring saved x/y), then place transitions/START/END at the
    // centroid of their neighbours so the alternation reads left→right.
    const pos: Record<string, { x: number; y: number }> = {}
    g.nodes.filter((n) => n.kind === 'step').forEach((n, i) => {
      pos[n.id] = { x: n.x ?? 220 + (i % 3) * 320, y: n.y ?? 120 + Math.floor(i / 3) * 190 }
    })
    const centroid = (id: string, fallback: { x: number; y: number }, dx = 0) => {
      const pts = g.edges
        .filter((e) => e.source === id || e.target === id)
        .map((e) => pos[e.source === id ? e.target : e.source])
        .filter(Boolean) as { x: number; y: number }[]
      pos[id] = pts.length
        ? { x: pts.reduce((s, p) => s + p.x, 0) / pts.length + dx, y: pts.reduce((s, p) => s + p.y, 0) / pts.length }
        : fallback
    }
    g.nodes.filter((n) => n.kind === 'transition' || n.kind === 'and' || n.kind === 'or').forEach((n) => centroid(n.id, { x: 360, y: 200 }))
    centroid(START_ID, { x: 60, y: 120 }, -170)
    centroid(END_ID, { x: 900, y: 200 }, 170)

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
      if (n.kind === 'transition')
        return { id: n.id, type: 'transition', position: pos[n.id], data: { condition: n.condition, label: n.condition ? summarize(n.condition) : undefined } satisfies TransitionNodeData }
      if (n.kind === 'and' || n.kind === 'or') return { id: n.id, type: n.kind, position: pos[n.id], data: {} }
      if (n.kind === 'start') return { id: n.id, type: 'start', deletable: false, position: pos[n.id], data: {} }
      return { id: n.id, type: 'end', deletable: false, position: pos[n.id], data: {} }
    })
    const rfEdges: Edge[] = g.edges.map((e, i) => arrow(e.source, e.target, `t${i}-${e.source}-${e.target}`))

    setHeader(recipe.definition.header)
    setFormula(recipe.definition.formula)
    setNodes(rfNodes)
    setEdges(rfEdges)
  }, [recipe, peas, peaById, procedureName, setNodes, setEdges])

  // GRAFCET alternation (with the AND/OR bars): which source→target links are legal.
  const ALLOWED: Record<string, string[]> = {
    start: ['step'],
    step: ['transition', 'and', 'or'],
    transition: ['step', 'and', 'or', 'end'],
    and: ['step', 'transition'],
    or: ['step', 'transition'],
    end: [],
  }
  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      const s = nodes.find((n) => n.id === c.source)?.type
      const t = nodes.find((n) => n.id === c.target)?.type
      if (!s || !t || c.source === c.target) return false
      if (!(ALLOWED[s] ?? []).includes(t)) return false
      // A bar's two sides must be opposite kinds — its "single" side (AND: one transition · OR: one
      // step) holds exactly one edge; its "many" side (the opposite kind) holds the branches. Reject
      // an edge that would make the sides the same kind (step→bar→step) or add a 2nd single-side edge.
      const sideKinds = (barId: string, side: 'in' | 'out') =>
        edges
          .filter((e) => (side === 'in' ? e.target : e.source) === barId)
          .map((e) => nodes.find((n) => n.id === (side === 'in' ? e.source : e.target))?.type)
          .filter(Boolean)
      const barOk = (barId: string, barType: string, newKind: string, side: 'in' | 'out') => {
        const singleKind = barType === 'and' ? 'transition' : 'step'
        const same = sideKinds(barId, side)
        const other = sideKinds(barId, side === 'in' ? 'out' : 'in')
        if (same.some((k) => k !== newKind)) return false // one side is homogeneous
        if (other.some((k) => k === newKind)) return false // the two sides are opposite kinds
        if (newKind === singleKind && same.length >= 1) return false // the single side takes only one
        return true
      }
      if ((t === 'and' || t === 'or') && !barOk(c.target!, t, s, 'in')) return false
      if ((s === 'and' || s === 'or') && !barOk(c.source!, s, t, 'out')) return false
      return true
    },
    [nodes, edges],
  )

  const onConnect = useCallback(
    (c: Connection) => {
      if (!isValidConnection(c)) return
      const key = `e-${c.source}-${c.target}-${Date.now()}`
      setEdges((es) => addEdge(arrow(c.source!, c.target!, key), es))
      // A transition's default guard = its (first) upstream step reaching COMPLETED — so a guard
      // shows the moment you wire a step into it, instead of a bare bar.
      const srcNode = nodes.find((n) => n.id === c.source)
      const tgtNode = nodes.find((n) => n.id === c.target)
      if (tgtNode?.type === 'transition' && srcNode?.type === 'step' && !(tgtNode.data as TransitionNodeData).condition) {
        const d = srcNode.data as StepNodeData
        const condition: Condition = { type: 'StateReached', pea_id: d.pea_id, service: d.service, state: 'COMPLETED' }
        setNodes((ns) => ns.map((n) => (n.id === tgtNode.id ? { ...n, data: { condition, label: summarize(condition) } } : n)))
      }
      setSaved(false)
    },
    [nodes, setEdges, setNodes, isValidConnection],
  )

  function updateTransitionCondition(nodeId: string, condition: Condition) {
    setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { condition, label: summarize(condition) } } : n)))
    setSaved(false)
  }
  function updateStepParams(nodeId: string, params: Record<string, number>) {
    setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, params } } : n)))
    setSaved(false)
  }

  function addStep(peaId: number, service: string, procedureId: number) {
    const id = nextStepId(nodes.filter((n) => n.type === 'step').map((n) => n.id))
    const position = dropPos.current ?? { x: 300, y: 160 }
    dropPos.current = null
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
  function addBlock(kind: 'transition' | 'and' | 'or', position = { x: 360, y: 180 }) {
    const id = `${kind}-${Date.now()}`
    setNodes((ns) => [...ns, { id, type: kind, position, data: {} }])
    setSaved(false)
  }

  // Palette: click drops in the middle; drag drops where released.
  function onQuickAdd(kind: PaletteKind) {
    if (kind === 'step') { dropPos.current = null; setAdding(true) }
    else addBlock(kind)
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
      if (kind === 'step') { dropPos.current = position; setAdding(true) }
      else addBlock(kind, position)
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
                isValidConnection={isValidConnection}
                onNodeDoubleClick={(_, node) => {
                  if (node.type === 'step') setEditingStep(node)
                  else if (node.type === 'transition') setEditingTransition(node)
                }}
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
                    nodeColor={(n) =>
                      n.type === 'transition' ? '#fbbf24'
                        : n.type === 'or' ? '#a78bfa'
                        : n.type === 'end' || n.type === 'start' ? '#2dd4bf'
                        : '#7c9cff'
                    }
                    className="!overflow-hidden !rounded-lg !border !border-edge"
                  />
                )}
              </ReactFlow>
              {nodes.filter((n) => n.type === 'step').length === 0 && (
                <div className="pointer-events-none absolute inset-0 grid place-items-center">
                  <p className="text-sm text-faint">Drag a <span className="text-dim">Step</span> from the top, then a <span className="text-warn">Transition</span> between steps.</p>
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

      {editingTransition && peas && (
        <ConditionEditor
          peas={peas}
          initial={(editingTransition.data as TransitionNodeData).condition ?? DEFAULT_COND}
          onClose={() => setEditingTransition(null)}
          onSave={(condition) => { updateTransitionCondition(editingTransition.id, condition); setEditingTransition(null) }}
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
