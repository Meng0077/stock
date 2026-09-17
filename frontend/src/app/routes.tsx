import { Navigate, Route, Routes } from 'react-router-dom'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ResearchPage } from '../pages/ResearchPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/research" replace />} />
      <Route path="/research" element={<ResearchPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
