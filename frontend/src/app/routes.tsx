import { Navigate, Route, Routes } from 'react-router-dom'
import type { RunTransport } from '../api/runTransport'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ResearchPage } from '../pages/ResearchPage'

interface AppRoutesProps {
  readonly runTransport: RunTransport
}

export function AppRoutes({ runTransport }: AppRoutesProps) {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/research" replace />} />
      <Route
        path="/research"
        element={<ResearchPage runTransport={runTransport} />}
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
