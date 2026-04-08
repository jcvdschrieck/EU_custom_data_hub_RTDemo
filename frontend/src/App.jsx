import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import EclLayout          from './components/EclLayout'
import MainPage           from './pages/MainPage'
import Dashboard          from './pages/Dashboard'
import SuspiciousPage     from './pages/SuspiciousPage'
import ProcessingLogPage  from './pages/ProcessingLogPage'
import SimulationPage     from './pages/SimulationPage'

export default function App() {
  return (
    <BrowserRouter>
      <EclLayout>
        <Routes>
          <Route path="/"             element={<Navigate to="/simulation" replace />} />
          <Route path="/main"         element={<MainPage />} />
          <Route path="/dashboard"    element={<Dashboard />} />
          <Route path="/suspicious"   element={<SuspiciousPage />} />
          <Route path="/agent-log"    element={<ProcessingLogPage />} />
          <Route path="/simulation"   element={<SimulationPage />} />
          <Route path="*"             element={<Navigate to="/simulation" replace />} />
        </Routes>
      </EclLayout>
    </BrowserRouter>
  )
}
