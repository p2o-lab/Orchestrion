import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
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
import {
  barSpans,
  branchRanks,
  branchSpawnPosition,
  defaultCondition,
  graphToTransitions,
  initialStepId,
  isPitTransition,
  recipeToGraph,
  reprioritise,
  selectionBranchMayDefault,
  transitionPositions,
  type BarSpan,
  type BranchAction,
  type GraphEdge,
  type GraphNode,
  type NodeKind,
} from '../ui/recipeGraph'
// `summarize` moved to `ui/conditions.ts` at unit 11a — it must recurse now that compounds
// are authorable, and the tree logic is pure and tested there.
import { summarize } from '../ui/conditions'
import { Icon } from '../ui/icons'
import { Button, Modal, Spinner } from '../ui/primitives'
import { StepNode, type StepNodeData } from './StepNode'
import { TransitionNode, type TransitionNodeData } from './FlowNodes'
import { BranchPriority } from './branchPriority'
import { ConditionEditor } from './ConditionEditor'
import { StepEditor } from './StepEditor'
import { RecipeSettings } from './RecipeSettings'
import { NodePalette, DRAG_KEY, type PaletteKind } from './NodePalette'

// Two node kinds. `and`/`or`/`start`/`end` were deleted at `010` unit 9 — AND/OR are link
// multiplicity (chart §4.3.2), the initial step is a double border (§2), and a branch ends by
// leaving a transition's output unwired (§3).
const nodeTypes = { step: StepNode, transition: TransitionNode }
const DEFAULT_COND: Condition = { type: 'Always' }

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

const arrow = (source: string, target: string, key: string): Edge => ({ id: key, source, target, ...EDGE })

// ── React Flow node/edge ⇄ the pure GraphNode/GraphEdge the mapping module speaks ──
function toGraphNode(n: Node): GraphNode {
  if (n.type === 'step') {
    const d = n.data as StepNodeData
    return { id: n.id, kind: 'step', pea_id: d.pea_id, service: d.service, procedure_id: d.procedure_id, params: d.params, x: n.position.x, y: n.position.y }
  }
  const d = n.data as TransitionNodeData
  return { id: n.id, kind: 'transition', condition: d.condition, priority: d.priority }
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
  /** Set by `addParallelBranch`, consumed by `addStep`: the transition the step being picked
   *  is a parallel branch of. A ref, not state, because it must survive the picker modal
   *  without re-rendering the canvas. */
  const branchFrom = useRef<string | null>(null)
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

    // Steps sit on a grid (honouring their saved x/y — the only stored coordinates). A
    // transition's place is a *function* of its neighbours (chart §9), so it is computed by
    // `transitionPositions`, never stored.
    const placed: GraphNode[] = g.nodes.map((n, i) =>
      n.kind === 'step'
        ? { ...n, x: n.x ?? 220 + (i % 3) * 320, y: n.y ?? 120 + Math.floor(i / 3) * 190 }
        : n,
    )
    const stepPos = new Map(placed.filter((n) => n.kind === 'step').map((n) => [n.id, { x: n.x!, y: n.y! }]))
    const trPos = transitionPositions(placed, g.edges)
    const initial = initialStepId(placed, g.edges)

    const rfNodes: Node[] = placed.map((n) => {
      if (n.kind === 'step')
        return {
          id: n.id, type: 'step', position: stepPos.get(n.id) ?? { x: 220, y: 120 },
          data: {
            pea_id: n.pea_id!, service: n.service!, procedure_id: n.procedure_id!, params: n.params ?? {},
            pea: peaById(n.pea_id!)?.name ?? `PEA ${n.pea_id}`,
            procedure: procedureName(n.pea_id!, n.service!, n.procedure_id!),
            isInitial: n.id === initial,
          } satisfies StepNodeData,
        }
      return {
        id: n.id, type: 'transition', position: trPos.get(n.id) ?? { x: 360, y: 200 },
        data: {
          condition: n.condition,
          label: n.condition ? summarize(n.condition) : undefined,
          isPit: isPitTransition(n.id, g.edges),
          // The saved list index, carried onto the canvas so a re-save reproduces the
          // author's branch order instead of reshuffling it (chart §8).
          priority: n.priority,
        } satisfies TransitionNodeData,
      }
    })
    const rfEdges: Edge[] = g.edges.map((e, i) => arrow(e.source, e.target, `t${i}-${e.source}-${e.target}`))

    setHeader(recipe.definition.header)
    setFormula(recipe.definition.formula)
    setNodes(rfNodes)
    setEdges(rfEdges)
  }, [recipe, peas, peaById, procedureName, setNodes, setEdges])

  // `isInitial` and `isPit` are **derived from topology**, not authored (chart §2, §3): adding
  // a step can move the initial marker, and wiring a transition's output un-caps its branch.
  // So they are recomputed on every graph change — and written back only when something
  // actually differs, or the state update would retrigger this effect for ever.
  useEffect(() => {
    const graphNodes = nodes.map(toGraphNode)
    const graphEdges = edges.map(toGraphEdge)
    const initial = initialStepId(graphNodes, graphEdges)
    // Bars span *where the branches sit* (§6), so they must be recomputed as nodes move —
    // dragging a branch step wider has to widen the bar with it.
    const live = new Map(nodes.map((n) => [n.id, { x: n.position.x, y: n.position.y }]))
    const bars = barSpans(graphNodes, graphEdges, live)
    // The ①②③ badge is derived too: wiring a second transition off a step *creates* a
    // selection, and deleting one dissolves it (chart §8).
    const ranks = branchRanks(graphNodes, graphEdges)
    const same = (a?: BarSpan, b?: BarSpan) =>
      a === b || (!!a && !!b && a.offsetY === b.offsetY && a.height === b.height && a.count === b.count)
    const sameRank = (a?: { rank: number; of: number }, b?: { rank: number; of: number }) =>
      a === b || (!!a && !!b && a.rank === b.rank && a.of === b.of)

    let changed = false
    const next = nodes.map((n) => {
      const bar = bars.get(n.id)
      const d = n.data as StepNodeData & TransitionNodeData
      const wantFlag = n.type === 'step' ? n.id === initial : isPitTransition(n.id, graphEdges)
      const flagKey = n.type === 'step' ? 'isInitial' : 'isPit'
      const found = ranks.get(n.id)
      const wantRank = found ? { rank: found.rank, of: found.of } : undefined
      if (
        d[flagKey] === wantFlag &&
        same(d.barIn, bar?.incoming) &&
        same(d.barOut, bar?.outgoing) &&
        sameRank(d.rank, wantRank)
      )
        return n
      changed = true
      return {
        ...n,
        data: { ...n.data, [flagKey]: wantFlag, barIn: bar?.incoming, barOut: bar?.outgoing, rank: wantRank },
      }
    })
    if (changed) setNodes(next)
  }, [nodes, edges, setNodes])

  /** Is this step's procedure self-completing? Straight off the PEA's parsed MTP
   *  ([2658-4:2022] Table 36 #4b) — it decides the default receptivity (chart §4). */
  const stepIsSelfCompleting = useCallback(
    (stepId: string) => {
      const d = nodes.find((n) => n.id === stepId)?.data as StepNodeData | undefined
      if (!d) return true
      const svc = peaById(d.pea_id)?.services.find((s) => s.name === d.service)
      return svc?.procedures.find((p) => p.procedure_id === d.procedure_id)?.is_self_completing ?? true
    },
    [nodes, peaById],
  )

  // §4.4 — "Step transition and transition step alternation **shall** always be respected
  // whatever the sequence." With the bars gone that rule is the whole table, so branching is
  // authored by wiring several links to one node rather than by placing anything.
  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      const s = nodes.find((n) => n.id === c.source)?.type
      const t = nodes.find((n) => n.id === c.target)?.type
      if (!s || !t || c.source === c.target) return false
      return (s === 'step' && t === 'transition') || (s === 'transition' && t === 'step')
    },
    [nodes],
  )

  const onConnect = useCallback(
    (c: Connection) => {
      if (!isValidConnection(c)) return
      const key = `e-${c.source}-${c.target}-${Date.now()}`
      const nextEdges = [...edges, arrow(c.source!, c.target!, key)]
      setEdges(nextEdges)

      const tgtNode = nodes.find((n) => n.id === c.target)
      if (tgtNode?.type === 'transition') {
        // Offer a default receptivity only where one is *valid*: `Always` when every
        // preceding step ends by itself (completion is gate #1, so there is nothing to add),
        // and **nothing** if any is continuous — there the receptivity IS the completion
        // criterion, so a default would complete the service the instant it started.
        const froms = nextEdges.filter((e) => e.target === tgtNode.id).map((e) => e.source)
        const condition = defaultCondition(froms, stepIsSelfCompleting)
        if (!(tgtNode.data as TransitionNodeData).condition) {
          setNodes((ns) =>
            ns.map((n) =>
              n.id === tgtNode.id
                ? {
                    ...n,
                    data: condition
                      ? { condition, label: summarize(condition), isPit: isPitTransition(n.id, nextEdges) }
                      : { isPit: isPitTransition(n.id, nextEdges), needsCondition: true },
                  }
                : n,
            ),
          )
        }
      }
      setSaved(false)
    },
    [nodes, edges, setEdges, setNodes, isValidConnection, stepIsSelfCompleting],
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
    // Set by `addParallelBranch`: the transition this new step is a branch of. Consumed here
    // because a step cannot exist until the picker has bound it to a procedure (§7 — the
    // action builds the *wiring*, it does not invent a node type).
    const from = branchFrom.current
    branchFrom.current = null
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
    if (from) setEdges((es) => [...es, arrow(from, id, `e-${from}-${id}-${Date.now()}`)])
    setSaved(false)
  }
  /** Drop a bare transition. It has no receptivity until a step is wired into it — only then
   *  is it known whether a default is even valid (chart §4). */
  function addBlock(kind: 'transition', position = { x: 360, y: 180 }) {
    const id = `${kind}-${Date.now()}`
    setNodes((ns) => [...ns, { id, type: kind, position, data: { isPit: true } satisfies TransitionNodeData }])
    setSaved(false)
  }

  // ── branch actions — chart §7 ─────────────────────────────────────────────────────────
  //
  // Neither action creates a node *type*: `parallel` adds a step, `selection` adds a
  // transition, and each adds one link. Alternation (§4.4) therefore holds by construction —
  // a transition can only spawn a step, a step can only spawn a transition.

  const livePositions = useCallback(
    () => new Map(nodes.map((n) => [n.id, { x: n.position.x, y: n.position.y }])),
    [nodes],
  )

  /** AND — [IEC 60848:2013] §6.2.6, one transition activating several sequences in parallel.
   *  Opens the step picker, because a step is meaningless until it is bound to a procedure;
   *  `branchFrom` carries the link across the modal. */
  function addParallelBranch(transitionId: string) {
    branchFrom.current = transitionId
    dropPos.current = branchSpawnPosition(transitionId, edges.map(toGraphEdge), livePositions())
    setAdding(true)
  }

  /** OR — §6.2.3, a step offering "as many simultaneously enabled transitions as possible
   *  evolutions". The new transition is a pit until it is wired onward (§3). */
  function addSelectionBranch(stepId: string) {
    const graphEdges = edges.map(toGraphEdge)
    const position = branchSpawnPosition(stepId, graphEdges, livePositions())
    const id = `transition-${Date.now()}`
    // A second branch never defaults to `Always`: its sibling would always win, so the branch
    // could never fire (§6.2.3's exclusivity duty, read through §8's priority arbitration).
    const condition = selectionBranchMayDefault(stepId, graphEdges)
      ? defaultCondition([stepId], stepIsSelfCompleting)
      : null
    setNodes((ns) => [
      ...ns,
      {
        id, type: 'transition', position,
        data: (condition
          ? { condition, label: summarize(condition), isPit: true }
          : { isPit: true, needsCondition: true }) satisfies TransitionNodeData,
      },
    ])
    setEdges((es) => [...es, arrow(stepId, id, `e-${stepId}-${id}-${Date.now()}`)])
    setSaved(false)
  }

  /** Raise or lower a branch's priority — chart §8. Swaps two `priority` keys, which changes
   *  where the two transitions land in `MasterRecipe.transitions`, which is exactly what the
   *  engine arbitrates on. Nothing else in the chart moves. */
  const moveBranch = useCallback(
    (transitionId: string, direction: 'up' | 'down') => {
      const graphEdges = edges.map(toGraphEdge)
      setNodes((ns) => {
        const moved = reprioritise(ns.map(toGraphNode), graphEdges, transitionId, direction)
        const byId = new Map(moved.map((n) => [n.id, n]))
        return ns.map((n) => {
          if (n.type !== 'transition') return n
          const next = byId.get(n.id)
          const d = n.data as TransitionNodeData
          if (!next || d.priority === next.priority) return n
          return { ...n, data: { ...n.data, priority: next.priority } }
        })
      })
      setSaved(false)
    },
    [edges, setNodes],
  )

  function onBranch(action: BranchAction) {
    const sel = nodes.filter((n) => n.selected)
    if (sel.length !== 1) return
    const node = sel[0]
    if (action === 'parallel' && node.type === 'transition') addParallelBranch(node.id)
    else if (action === 'selection' && node.type === 'step') addSelectionBranch(node.id)
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

      {recipe && peas && (
        <NodePalette
          onQuickAdd={onQuickAdd}
          // Exactly one selection, or the action has no unambiguous owner.
          selectedKind={
            nodes.filter((n) => n.selected).length === 1
              ? ((nodes.find((n) => n.selected)!.type ?? null) as NodeKind | null)
              : null
          }
          onBranch={onBranch}
        />
      )}
      <div className="relative flex-1" onDrop={onDrop} onDragOver={onDragOver}>
        {recipe === null || peas === null ? (
          <div className="grid h-full place-items-center">
            {error ? <p className="text-sm text-danger">{error}</p> : <Spinner className="h-6 w-6" />}
          </div>
        ) : (
          <BranchPriority.Provider value={moveBranch}>
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
                      n.type === 'transition'
                        ? '#fbbf24'
                        : (n.data as StepNodeData)?.isInitial
                          ? '#2dd4bf'   // the initial step, matching its double border
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
            </BranchPriority.Provider>
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
          // `Always` is only offered when every preceding step ends by itself — on a
          // continuous procedure the receptivity IS the completion criterion (chart §4/§5).
          allowAlways={edges
            .filter((e) => e.target === editingTransition.id)
            .every((e) => stepIsSelfCompleting(e.source))}
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
