import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './context'

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex h-full items-center justify-center p-8 text-muted">{children}</div>
}

function AuthError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <Centered>
      <div className="max-w-md text-ink">
        <h1 className="text-xl font-semibold">Can't reach the Shiftwright server</h1>
        <p className="mt-2 text-ink-2">{message}</p>
        {import.meta.env.DEV && (
          <p className="mt-2 text-sm text-muted">
            Start the API on port 8000, or open this page with <code>?api=mock</code> to use the built-in mock.
          </p>
        )}
        <button type="button" className="mt-4 rounded-md bg-ink px-4 py-2 font-semibold text-white" onClick={retry}>
          Try again
        </button>
      </div>
    </Centered>
  )
}

/** App routes: signed-out visitors go to /login and come back here afterwards. */
export function RequireAuth() {
  const { state, retry } = useAuth()
  const location = useLocation()
  if (state.status === 'loading') return <Centered>Loading…</Centered>
  if (state.status === 'error') return <AuthError message={state.message} retry={retry} />
  if (state.status === 'out')
    return <Navigate to="/login" replace state={state.signedOut ? null : { from: location.pathname + location.search }} />
  return <Outlet />
}

/** /login and /signup wait for the session check (the pages send signed-in visitors on themselves). */
export function GuestOnly() {
  const { state, retry } = useAuth()
  if (state.status === 'loading') return <Centered>Loading…</Centered>
  if (state.status === 'error') return <AuthError message={state.message} retry={retry} />
  return <Outlet />
}
