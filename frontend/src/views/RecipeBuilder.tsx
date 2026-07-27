import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api/client'
import type { RecipeDetail } from '../api/types'
import { Icon } from '../ui/icons'
import { Spinner } from '../ui/primitives'

// Recipe → React Flow graph. Steps have no stored layout yet (persisted positions land in a
// later sub-unit), so lay them out on a simple grid for now. `END` targets are not nodes.
function toGraph(recipe: RecipeDetail): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = recipe.definition.steps.map((step, i) => ({
    id: step.id,
    position: { x: 80 + (i % 4) * 240, y: 80 + Math.floor(i / 4) * 160 },
    data: { label: `${step.service} · #${step.procedure_id}` },
  }))
  const edges: Edge[] = recipe.definition.transitions.flatMap((t, ti) =>
    t.from_ids.flatMap((from) =>
      t.to_ids
        .filter((to) => to !== 'END')
        .map((to) => ({ id: `t${ti}-${from}-${to}`, source: from, target: to })),
    ),
  )
  return { nodes, edges }
}

export function RecipeBuilder() {
  const { projectId, recipeId } = useParams()
  const pid = Number(projectId)
  const rid = Number(recipeId)
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRecipe(null)
    setError(null)
    api.getRecipe(pid, rid).then(setRecipe).catch((e) => setError(String(e?.message ?? e)))
  }, [pid, rid])

  const graph = recipe ? toGraph(recipe) : { nodes: [], edges: [] }

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <div className="flex items-center justify-between border-b border-edge px-8 py-4">
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
        {recipe && (
          <div className="text-xs text-faint">
            {recipe.step_count} step{recipe.step_count === 1 ? '' : 's'} · v{recipe.version}
          </div>
        )}
      </div>

      {/* canvas */}
      <div className="relative flex-1">
        {recipe === null ? (
          <div className="grid h-full place-items-center">
            {error ? <p className="text-sm text-danger">{error}</p> : <Spinner className="h-6 w-6" />}
          </div>
        ) : (
          <>
            <ReactFlow nodes={graph.nodes} edges={graph.edges} colorMode="dark" fitView minZoom={0.2}>
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
            {recipe.definition.steps.length === 0 && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center">
                <p className="text-sm text-faint">Empty recipe — step tools coming next.</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
