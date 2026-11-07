import { createContext, useContext } from 'react'
import type { User } from '../api/protocol'

export type AuthState =
  | { status: 'loading' }
  | { status: 'in'; user: User }
  /** `signedOut`: the user pressed Sign out (vs. a missing or expired session). */
  | { status: 'out'; signedOut?: boolean }
  | { status: 'error'; message: string }

export type Auth = {
  state: AuthState
  /** After a successful signup/login response. */
  signedIn: (user: User) => void
  signOut: () => Promise<void>
  retry: () => void
}

export const AuthContext = createContext<Auth | null>(null)

export function useAuth(): Auth {
  const a = useContext(AuthContext)
  if (!a) throw new Error('useAuth outside <AuthProvider>')
  return a
}
