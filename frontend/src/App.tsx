import { useEffect, useState } from 'react'

type Health = { status: string }

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function checkHealth() {
      try {
        const response = await fetch('/api/health')
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data: Health = await response.json()
        if (!cancelled) setHealth(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }

    void checkHealth()

    // StrictMode invokes effects twice in dev; this keeps the discarded run from
    // writing state after its component instance is gone.
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main>
      <h1>Orchestrion</h1>
      <p>
        Backend:{' '}
        {error !== null ? `unreachable — ${error}` : (health?.status ?? 'checking…')}
      </p>
    </main>
  )
}

export default App
