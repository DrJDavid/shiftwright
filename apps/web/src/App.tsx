import { useCallback, useEffect, useState } from 'react'
import { api, apiMode } from './api'
import { ApiError } from './api/client'
import type { Readiness, SolveResponse } from './api/protocol'
import type { StoreConfig } from './contracts'
import { ChatPane } from './components/ChatPane'
import { ReadinessRail } from './components/ReadinessRail'
import { ScheduleTab } from './components/ScheduleTab'
import type { SolveState } from './components/SolveButton'
import { fmtDayDate } from './lib/format'

type Tab = 'schedule' | 'coverage' | 'fix'
const TABS: { id: Tab; label: string; ready: boolean }[] = [
  { id: 'schedule', label: 'Schedule', ready: true },
  { id: 'coverage', label: 'Coverage', ready: false },
  { id: 'fix', label: 'Fix call-outs', ready: false },
]

const STORE_KEY = `sw.storeId.${apiMode}`
const NEW_STORE = {
  template: (import.meta.env.VITE_STORE_TEMPLATE as 'bigbox_small' | 'bigbox_mid' | 'empty' | undefined) ?? 'bigbox_mid',
  name: 'Store #0417',
  jurisdiction: { state: 'TX', city: 'austin' },
}

async function loadOrCreateStore(): Promise<StoreConfig> {
  let saved: string | null = null
  try {
    saved = localStorage.getItem(STORE_KEY)
  } catch {
    /* storage unavailable */
  }
  if (saved) {
    try {
      return await api.getConfig(saved)
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err
    }
  }
  const cfg = await api.createStore(NEW_STORE)
  try {
    localStorage.setItem(STORE_KEY, cfg.store.id)
  } catch {
    /* storage unavailable */
  }
  return cfg
}

export default function App() {
  const [config, setConfig] = useState<StoreConfig | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [readinessError, setReadinessError] = useState<string | null>(null)
  const [result, setResult] = useState<SolveResponse | null>(null)
  const [solve, setSolve] = useState<SolveState>({ status: 'idle' })
  const [tab, setTab] = useState<Tab>('schedule')
  const [railOpen, setRailOpen] = useState(true)
  const storeId = config?.store.id

  useEffect(() => {
    loadOrCreateStore()
      .then(setConfig)
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  const refreshReadiness = useCallback(async (id: string) => {
    try {
      setReadiness(await api.readiness(id))
      setReadinessError(null)
    } catch (e) {
      setReadinessError((e as Error).message)
    }
  }, [])

  const refreshSchedule = useCallback(async (id: string) => {
    try {
      setResult(await api.latestSchedule(id))
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) setSolve({ status: 'error', message: (e as Error).message })
    }
  }, [])

  useEffect(() => {
    if (!storeId) return
    void refreshReadiness(storeId)
    void refreshSchedule(storeId)
  }, [storeId, refreshReadiness, refreshSchedule])

  const onConfigChanged = useCallback(async () => {
    if (!storeId) return
    try {
      setConfig(await api.getConfig(storeId))
    } catch (e) {
      setLoadError((e as Error).message)
    }
    void refreshReadiness(storeId)
  }, [storeId, refreshReadiness])

  const runSolve = useCallback(async () => {
    if (!storeId) return
    setSolve({ status: 'running', startedAt: Date.now() })
    setTab('schedule')
    try {
      setResult(await api.solve(storeId))
      setSolve({ status: 'idle' })
      setRailOpen(false) // give the week grid the room
    } catch (e) {
      setSolve({ status: 'error', message: (e as Error).message })
    }
  }, [storeId])

  if (loadError && !config) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md">
          <h1 className="text-xl font-semibold">Can't reach the Shiftwright server</h1>
          <p className="mt-2 text-ink-2">{loadError}</p>
          <p className="mt-2 text-sm text-muted">
            Start the API on port 8000, or open this page with <code>?api=mock</code> to use the built-in mock.
          </p>
          <button type="button" className="mt-4 rounded-md bg-ink px-4 py-2 font-semibold text-white" onClick={() => location.reload()}>
            Try again
          </button>
        </div>
      </div>
    )
  }
  if (!config) {
    return <div className="flex h-full items-center justify-center text-muted">Loading store…</div>
  }

  const week = fmtDayDate(config.store.week_start, 0)
  const end = fmtDayDate(config.store.week_start, 6)
  const juris = config.store.jurisdiction

  return (
    <div className="grid h-full grid-rows-[auto_1fr]">
      <header className="flex items-center gap-4 border-b border-ink bg-ink px-4 py-2 text-white">
        <span className="font-bold tracking-tight">Shiftwright</span>
        <span className="h-5 w-px bg-white/25" aria-hidden />
        <span className="font-medium">{config.store.name}</span>
        <span className="text-white/70">
          {juris.city ? `${juris.city.replace(/\b\w/g, (c) => c.toUpperCase())}, ` : ''}
          {juris.state}
        </span>
        <span className="text-white/70">
          Week of {week.date} to {end.date}
        </span>
        {apiMode === 'mock' && (
          <span
            className="ml-auto rounded border border-amber-300/60 bg-amber-300/15 px-2 py-0.5 text-xs font-semibold text-amber-200"
            title="Data comes from the in-browser mock API, not the solver. Open with ?api=live to use the real server."
          >
            Mock API
          </span>
        )}
      </header>

      <div className={`grid min-h-0 ${railOpen ? 'grid-cols-[minmax(340px,35%)_1fr_17rem]' : 'grid-cols-[minmax(340px,35%)_1fr_3rem]'}`}>
        <ChatPane
          api={api}
          storeId={config.store.id}
          mode="onboard"
          onConfigChanged={() => void onConfigChanged()}
          onScheduleChanged={() => void refreshSchedule(config.store.id)}
        />

        <main className="flex min-h-0 min-w-0 flex-col bg-panel">
          <nav className="flex gap-1 border-b border-rule px-3" role="tablist" aria-label="Views">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                disabled={!t.ready}
                title={t.ready ? undefined : 'Not built yet'}
                onClick={() => setTab(t.id)}
                className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-semibold ${
                  tab === t.id ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
                } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-muted`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          {tab === 'schedule' && <ScheduleTab config={config} result={result} solve={solve} onSolve={() => void runSolve()} />}
        </main>

        <ReadinessRail
          readiness={readiness}
          error={readinessError}
          solve={solve}
          onSolve={() => void runSolve()}
          open={railOpen}
          onToggle={() => setRailOpen((o) => !o)}
        />
      </div>
    </div>
  )
}
