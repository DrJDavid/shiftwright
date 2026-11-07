import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const gallery = import.meta.env.DEV && new URLSearchParams(location.search).has('gallery')
const CardGallery = lazy(() => import('./dev/CardGallery').then((m) => ({ default: m.CardGallery })))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {gallery ? (
      <Suspense fallback={null}>
        <CardGallery />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
)
