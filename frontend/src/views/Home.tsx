import { Link } from 'react-router-dom'
import { useWorkspace } from '../workspace'
import { Card, Spinner } from '../ui/primitives'
import { Icon } from '../ui/icons'

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
    <div className="w-full px-10 py-12">
      {/* hero */}
      <div className="animate-rise">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-edge bg-white/4 px-3 py-1 text-xs text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-st-execute pulse-dot" />
          Modular process orchestration
        </div>
        <h1 className="bg-gradient-to-br from-ink to-dim bg-clip-text text-4xl font-semibold text-transparent">
          Welcome to Orchestrion
        </h1>
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-dim">
          A process orchestration layer for MTP-based modular plants. Create a project — a
          plant configuration — then import the module type packages of your PEAs to inspect,
          connect to, and control them.
        </p>
      </div>

      {projects.length > 0 ? (
        <div className="mt-12">
          <div className="mb-4 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
            <Icon name="folder" size={14} /> Your projects
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {projects.map((p, i) => (
              <Link key={p.id} to={`/projects/${p.id}`} className="animate-rise" style={{ animationDelay: `${i * 45}ms` }}>
                <Card className="edge-top-accent group p-5 transition duration-200 hover:-translate-y-1 hover:border-accent/40 hover:shadow-[0_20px_50px_-12px_rgba(0,0,0,0.6)]">
                  <div className="flex items-start justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/12 text-accent transition group-hover:bg-accent/20">
                      <Icon name="folder" size={20} />
                    </span>
                    <Icon name="chevron" size={18} className="text-faint transition group-hover:translate-x-0.5 group-hover:text-accent" />
                  </div>
                  <div className="mt-4 text-base font-semibold text-ink">{p.name}</div>
                  <div className="mt-1 text-sm text-faint">
                    {p.pea_count} module{p.pea_count === 1 ? '' : 's'}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ) : (
        <Card className="mt-12 flex flex-col items-center gap-3 p-14 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-accent/12 text-accent">
            <Icon name="folder" size={26} />
          </span>
          <p className="text-dim">
            No projects yet — use <span className="text-accent">+</span> in the sidebar to create
            your first one.
          </p>
        </Card>
      )}
    </div>
  )
}
