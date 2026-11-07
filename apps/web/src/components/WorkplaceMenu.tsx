import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useApi } from '../api/context'
import type { WorkplaceSummary } from '../api/protocol'
import { useAuth } from '../auth/context'
import { isSample, placeLabel, useSampleTemplates } from '../lib/stores'
import { useOpenSample } from '../pages/useOpenSample'

/** Header menu: my workplaces (current one checked), + New workplace, Explore a sample, Sign out. */
export function WorkplaceMenu({ currentId }: { currentId: string }) {
  const api = useApi()
  const auth = useAuth()
  const navigate = useNavigate()
  const samples = useSampleTemplates(api)
  const sample = useOpenSample()
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<WorkplaceSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let live = true
    api
      .workplaces()
      .then((r) => live && setList(r.workplaces))
      .catch((e: Error) => live && setError(e.message))
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    window.addEventListener('mousedown', close)
    return () => {
      live = false
      window.removeEventListener('mousedown', close)
    }
  }, [api, open])

  const go = (id: string) => {
    setOpen(false)
    if (id !== currentId) navigate(`/w/${encodeURIComponent(id)}`)
  }
  const mine = list?.filter((w) => !isSample(w.name)) ?? []
  const sampleCopies = list?.filter((w) => isSample(w.name)) ?? []
  const user = auth.state.status === 'in' ? auth.state.user : null

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((o) => !o)}
        className="rounded border border-white/30 px-2.5 py-1 text-sm font-medium text-white/90 hover:border-white hover:text-white"
      >
        {sample.busy ? 'Opening sample…' : 'My workplaces ▾'}
      </button>
      {open && (
        <div role="menu" className="absolute top-full right-0 z-50 mt-1.5 w-80 rounded-lg border border-rule bg-panel p-1.5 text-ink shadow-xl">
          <SectionLabel>My workplaces</SectionLabel>
          {!list && !error && <p className="px-2.5 py-1.5 text-sm text-muted">Loading…</p>}
          {error && <p className="px-2.5 py-1.5 text-xs text-gap">Couldn't load your workplaces: {error}</p>}
          {list && mine.length === 0 && <p className="px-2.5 py-1.5 text-sm text-muted">None yet.</p>}
          {mine.map((w) => (
            <WorkplaceItem key={w.id} w={w} current={w.id === currentId} onClick={() => go(w.id)} />
          ))}
          <Link
            role="menuitem"
            to="/workplaces/new"
            onClick={() => setOpen(false)}
            className="block rounded-md px-2.5 py-2 text-sm font-semibold text-pine-dark hover:bg-paper"
          >
            + New workplace
          </Link>

          <div className="my-1 border-t border-rule-soft" />
          <SectionLabel>Explore a sample</SectionLabel>
          {sampleCopies.map((w) => (
            <WorkplaceItem key={w.id} w={w} current={w.id === currentId} onClick={() => go(w.id)} />
          ))}
          {samples.map((t) => (
            <button
              key={t.template}
              type="button"
              role="menuitem"
              disabled={!!sample.busy}
              onClick={() => void sample.open(t).then(() => setOpen(false))}
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-paper disabled:opacity-50"
            >
              {sample.busy === t.template ? 'Opening…' : `New sample: ${t.label}`}
            </button>
          ))}
          {sample.error && <p className="px-2.5 py-1 text-xs text-gap">{sample.error}</p>}

          <div className="my-1 border-t border-rule-soft" />
          <div className="flex items-center gap-2 px-2.5 py-1.5">
            {user && <span className="min-w-0 truncate text-xs text-muted">{user.email}</span>}
            <span className="ml-auto" />
            <button
              type="button"
              role="menuitem"
              className="rounded px-2 py-1 text-sm font-semibold hover:bg-paper"
              onClick={() => void auth.signOut()}
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function SectionLabel({ children }: { children: string }) {
  return <div className="px-2.5 pt-1 pb-0.5 text-xs font-semibold tracking-wide text-muted uppercase">{children}</div>
}

function WorkplaceItem({ w, current, onClick }: { w: WorkplaceSummary; current: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={current}
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left hover:bg-paper"
    >
      <span className="w-4 shrink-0 text-pine" aria-hidden>
        {current ? '✓' : ''}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold">{w.name}</span>
        <span className="block text-xs text-muted">{placeLabel(w.city, w.state)}</span>
      </span>
    </button>
  )
}
