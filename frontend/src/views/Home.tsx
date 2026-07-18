import { Link } from 'react-router-dom'
import { useWorkspace } from '../workspace'
import { Card, Spinner } from '../ui/primitives'

export function Home() {
  const { projects, loading } = useWorkspace()

  if (loading) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner className="h-6 w-6" />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-10 py-16">
      <div className="animate-fade-in">
        <h1 className="text-3xl text-ink">Welcome to Orchestrion</h1>
        <p className="mt-3 max-w-xl text-dim">
          A process orchestration layer for MTP-based modular plants. Create a project — a
          plant configuration — then import the module type packages of your PEAs to inspect
          and control them.
        </p>
      </div>

      {projects.length > 0 && (
        <div className="mt-10">
          <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-faint">
            Your projects
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`}>
                <Card className="p-5 transition hover:border-accent/40">
                  <div className="text-base font-semibold text-ink">{p.name}</div>
                  <div className="mt-1 text-sm text-faint">
                    {p.pea_count} PEA{p.pea_count === 1 ? '' : 's'}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      )}

      {projects.length === 0 && (
        <Card className="mt-10 p-8 text-center">
          <p className="text-dim">
            No projects yet — use <span className="text-accent">+</span> in the sidebar to create
            your first one.
          </p>
        </Card>
      )}
    </div>
  )
}
