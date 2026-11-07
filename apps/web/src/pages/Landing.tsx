import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'

const PROOF = [
  { title: 'Builds the week in seconds', detail: 'Coverage, budget and everyone’s availability, balanced for the lowest cost.' },
  { title: 'Follows the labor law where you are', detail: 'Uses the labor rules for your city and state, each with its citation.' },
  { title: 'Fixes call-outs and texts your team', detail: 'Someone calls out, Shiftwright finds cover and asks them for you.' },
]

export function Landing() {
  const { state } = useAuth()
  const signedIn = state.status === 'in'
  return (
    <div className="flex min-h-full flex-col bg-paper">
      <header className="flex items-center gap-4 px-8 py-5">
        <span className="text-lg font-bold tracking-tight">Shiftwright</span>
        <span className="ml-auto" />
        {signedIn ? (
          <Link to="/workplaces" className="text-sm font-semibold text-ink-2 hover:text-ink">
            My workplaces
          </Link>
        ) : (
          <Link to="/login" className="text-sm font-semibold text-ink-2 hover:text-ink">
            Sign in
          </Link>
        )}
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-8 pb-20">
        <h1 className="max-w-3xl text-5xl leading-[1.1] font-semibold tracking-tight text-ink">
          Legal, lowest-cost schedules for hourly teams, in minutes.
        </h1>
        <div className="mt-10 flex gap-3">
          {signedIn ? (
            <Link to="/workplaces" className="rounded-md bg-pine px-5 py-3 font-semibold text-white hover:bg-pine-dark">
              Go to my workplaces
            </Link>
          ) : (
            <>
              <Link to="/signup" className="rounded-md bg-pine px-5 py-3 font-semibold text-white hover:bg-pine-dark">
                Get started
              </Link>
              <Link to="/login" className="rounded-md border border-ink/25 bg-panel px-5 py-3 font-semibold text-ink hover:border-ink">
                Sign in
              </Link>
            </>
          )}
        </div>
        <ul className="mt-16 grid grid-cols-1 gap-6 border-t border-rule pt-8 md:grid-cols-3">
          {PROOF.map((p) => (
            <li key={p.title} className="border-l-2 border-pine pl-4">
              <span className="block font-semibold text-ink">{p.title}</span>
              <span className="mt-1 block text-sm text-ink-2">{p.detail}</span>
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
