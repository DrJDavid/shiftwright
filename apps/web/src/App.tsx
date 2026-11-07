import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { GuestOnly, RequireAuth } from './auth/guards'
import { AuthPage } from './pages/AuthPage'
import { Landing } from './pages/Landing'
import { NewWorkplace } from './pages/NewWorkplace'
import { Workplaces } from './pages/Workplaces'
import { Workspace } from './Workspace'

function WorkspaceRoute() {
  const { id = '' } = useParams()
  return <Workspace key={id} storeId={id} />
}

/** Needs a router, an <AuthProvider> and (optionally) an ApiContext above it; see main.tsx. */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route element={<GuestOnly />}>
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route path="/workplaces" element={<Workplaces />} />
        <Route path="/workplaces/new" element={<NewWorkplace />} />
        <Route path="/w/:id" element={<WorkspaceRoute />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
