import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import EclLayout from './components/EclLayout'
import MainPage  from './pages/MainPage'
import Dashboard from './pages/Dashboard'

export default function App() {
  return (
    <BrowserRouter>
      <EclLayout>
        <Routes>
          <Route path="/"          element={<MainPage />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="*"          element={<Navigate to="/" replace />} />
        </Routes>
      </EclLayout>
    </BrowserRouter>
  )
}
