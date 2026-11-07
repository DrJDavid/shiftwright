import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'

/** Top-right of the signed-in pages outside the workspace. */
export function AccountLinks() {
  const auth = useAuth()
  const user = auth.state.status === 'in' ? auth.state.user : null
  return (
    <span className="flex items-center gap-4 text-sm">
      <Link to="/workplaces" className="text-white/80 hover:text-white">
        My workplaces
      </Link>
      {user && <span className="text-white/60">{user.name || user.email}</span>}
      <button
        type="button"
        className="rounded border border-white/30 px-2.5 py-1 font-medium text-white/90 hover:border-white hover:text-white"
        onClick={() => void auth.signOut()}
      >
        Sign out
      </button>
    </span>
  )
}
