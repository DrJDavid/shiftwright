import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import type { WorkplaceSummary } from '../api/protocol'
import { isSample, placeLabel, sectorLabel, useSampleTemplates } from '../lib/stores'
import { AccountLinks } from './AccountLinks'
import { PageShell } from './Shell'
import { readableError } from './ui'
import { useOpenSample } from './useOpenSample'

export function Workplaces() {
  const api = useApi()
  const samples = useSampleTemplates(api)
  const sample = useOpenSample()
  const [list, setList] = useState<WorkplaceSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .workplaces()
      .then((r) => live && setList(r.workplaces))
      .catch((e) => live && setError(readableError(e, 'Couldn’t load your workplaces.')))
    return () => {
      live = false
    }
  }, [api])

  const mine = list?.filter((w) => !isSample(w)) ?? []
  const sampleCopies = list?.filter((w) => isSample(w)) ?? []

  return (
    <PageShell wide right={<AccountLinks />}>
      <div className="flex items-end gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">My workplaces</h1>
        <span className="ml-auto" />
        <Link to="/workplaces/new" className="rounded-md bg-pine px-4 py-2 font-semibold text-white hover:bg-pine-dark">
          + New workplace
        </Link>
      </div>

      {error && <p className="mt-6 rounded-md bg-gap-wash px-3 py-2 text-sm text-gap">{error}</p>}
      {!list && !error && <p className="mt-6 text-muted">Loading…</p>}
      {list && mine.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed border-rule bg-panel px-6 py-10 text-center">
          <p className="font-semibold">No workplaces yet.</p>
          <p className="mt-1 text-sm text-ink-2">Create one and the chat walks you through setup.</p>
          <Link to="/workplaces/new" className="mt-4 inline-block font-semibold text-pine-dark underline">
            Create your first workplace
          </Link>
        </div>
      )}
      {mine.length > 0 && <WorkplaceList items={mine} />}

      <section className="mt-10">
        <h2 className="text-sm font-semibold tracking-wide text-muted uppercase">Explore a sample</h2>
        {sampleCopies.length > 0 && <WorkplaceList items={sampleCopies} />}
        <div className="mt-3 flex flex-wrap gap-2">
          {samples.map((t) => (
            <button
              key={t.template}
              type="button"
              disabled={!!sample.busy}
              onClick={() => void sample.open(t)}
              className="rounded-md border border-rule bg-panel px-3 py-2 text-sm font-medium hover:border-ink-2 disabled:opacity-50"
            >
              {sample.busy === t.template ? 'Opening…' : `Open a sample: ${t.label}`}
            </button>
          ))}
        </div>
        {sample.error && <p className="mt-2 text-sm text-gap">{sample.error}</p>}
      </section>
    </PageShell>
  )
}

function WorkplaceList({ items }: { items: WorkplaceSummary[] }) {
  return (
    <ul className="mt-4 divide-y divide-rule-soft overflow-hidden rounded-lg border border-rule bg-panel">
      {items.map((w) => (
        <li key={w.id}>
          <Link to={`/w/${encodeURIComponent(w.id)}`} className="flex items-center gap-4 px-5 py-4 hover:bg-paper">
            <span className="min-w-0">
              <span className="block truncate font-semibold">{w.name}</span>
              <span className="block text-sm text-ink-2">
                {[sectorLabel(w.sector), placeLabel(w.city, w.state)].filter(Boolean).join(' · ')}
              </span>
            </span>
            <span className="ml-auto" />
            <span
              className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                w.has_schedule ? 'bg-pine-wash text-pine-dark' : 'bg-warn-wash text-warn'
              }`}
            >
              {w.has_schedule ? 'Schedule built' : 'Setting up'}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
