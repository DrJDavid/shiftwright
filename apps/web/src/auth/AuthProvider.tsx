import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authEvents } from '../api'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import type { User } from '../api/protocol'
import { AuthContext, type AuthState } from './context'

/** Asks `/api/auth/me` once; any later 401 from the API signs the page out. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const api = useApi()
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    api
      .me()
      .then((r) => live && setState({ status: 'in', user: r.user }))
      .catch((e: Error) => {
        if (!live) return
        if (e instanceof ApiError && e.status === 401) setState({ status: 'out' })
        else setState({ status: 'error', message: e.message })
      })
    return () => {
      live = false
    }
  }, [api, attempt])

  useEffect(() => {
    const out = () => setState({ status: 'out' })
    authEvents.addEventListener('unauthorized', out)
    return () => authEvents.removeEventListener('unauthorized', out)
  }, [])

  const signedIn = useCallback((user: User) => setState({ status: 'in', user }), [])
  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setState({ status: 'out', signedOut: true })
    }
  }, [api])
  const retry = useCallback(() => {
    setState({ status: 'loading' })
    setAttempt((n) => n + 1)
  }, [])

  const value = useMemo(() => ({ state, signedIn, signOut, retry }), [state, signedIn, signOut, retry])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
