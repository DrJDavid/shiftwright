import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthProvider'
import { EmployeeApp } from './components/EmployeeApp'

const params = new URLSearchParams(location.search)
const gallery = import.meta.env.DEV && params.has('gallery')
const employee = params.get('employee')
const CardGallery = lazy(() => import('./dev/CardGallery').then((m) => ({ default: m.CardGallery })))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {employee ? (
      <EmployeeApp employeeId={employee} />
    ) : gallery ? (
      <Suspense fallback={null}>
        <CardGallery />
      </Suspense>
    ) : (
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    )}
  </StrictMode>,
)
