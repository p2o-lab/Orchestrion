import { Navigate, Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { WorkspaceProvider } from './workspace'
import { Home } from './views/Home'
import { ProjectView } from './views/ProjectView'
import { PeaView } from './views/PeaView'

export default function App() {
  return (
    <WorkspaceProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/projects/:projectId" element={<ProjectView />} />
            <Route path="/projects/:projectId/peas/:peaId" element={<PeaView />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </WorkspaceProvider>
  )
}
