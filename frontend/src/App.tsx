import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { WorkspaceProvider } from './workspace'
import { Home } from './views/Home'
import { ProjectView } from './views/ProjectView'
import { PeaView } from './views/PeaView'
import { LogWindow } from './views/LogWindow'

// The app shell: sidebar + the main routed content. A pathless layout route wraps
// the normal pages so the log window can live OUTSIDE it (its own bare browser
// window, no sidebar) — see LogWindow / PeaView.openLog.
function Shell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <WorkspaceProvider>
      <Routes>
        {/* Standalone: the event log in its own window, without the shell. */}
        <Route path="/projects/:projectId/peas/:peaId/log" element={<LogWindow />} />
        <Route element={<Shell />}>
          <Route path="/" element={<Home />} />
          <Route path="/projects/:projectId" element={<ProjectView />} />
          <Route path="/projects/:projectId/peas/:peaId" element={<PeaView />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  )
}
