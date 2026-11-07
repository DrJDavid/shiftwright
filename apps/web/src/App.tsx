import { useCallback, useEffect, useState } from 'react'
import { api, apiMode } from './api'
import { ApiError } from './api/client'
import type { Readiness, SolveResponse } from './api/protocol'
import type { Gap, LawPack, StoreConfig } from './contracts'
import { ChatPane } from './components/ChatPane'
import { CoverageTab } from './components/CoverageTab'
import { FixTab } from './components/FixTab'
import { GapSheet } from './components/GapSheet'
import { ReadinessRail } from './components/ReadinessRail'
import { Rulebook } from './components/Rulebook'
import { ScheduleTab } from './components/ScheduleTab'
import { StoreMenu } from './components/StoreMenu'
import { StoreTab } from './components/StoreTab'
import { ReceiptTab } from './components/ReceiptTab'
import type { SolveState } from './components/SolveButton'
import { fmtDayDate } from './lib/format'
import { createStore, STORE_KEY, templateFromDemoParam } from './lib/stores'

type Tab = 'schedule' | 'coverage' | 'store' | 'fix' | 'receipt'
const TABS: { id: Tab; label: string; ready: boolean }[] = [
  { id: 'schedule', label: 'Schedule', ready: true },
  { id: 'coverage', label: 'Coverage', ready: true },
  { id: 'store', label: 'Store', ready: true },
  { id: 'fix', label: 'Fix call-outs', ready: true },
  { id: 'receipt', label: 'Compliance receipt', ready: true },
]

// Once per page load: React StrictMode runs effects twice in dev, and a second run (after `?demo` was
// stripped from the URL) used to create an empty store that replaced the demo one.
let initialStore: Promise<StoreConfig> | null = null
function loadOrCreateStoreOnce(): Promise<StoreConfig> {
  initialStore ??= loadOrCreateStore()
  return initialStore
}

async function loadOrCreateStore(): Promise<StoreConfig> {
  // ?demo in the URL: start from a fresh copy of the demo store.
  const url = new URL(window.location.href)
  const demo = url.searchParams.get('demo')
  if (demo !== null) {
    url.searchParams.delete('demo')
    window.history.replaceState(null, '', url)
    return createStore(templateFromDemoParam(demo))
  }
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
  return createStore('empty')
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
  const [chatOpen, setChatOpen] = useState(true)
  const [openGap, setOpenGap] = useState<Gap | null>(null)
  const [coverageDay, setCoverageDay] = useState(0)
  const [callouts, setCallouts] = useState<{ employee_id: string; day: number }[]>([])
  const [lawPack, setLawPack] = useState<LawPack | null>(null)
  const [lawError, setLawError] = useState<string | null>(null)
  const storeId = config?.store.id
  const lawState = config?.store.jurisdiction.state
  const lawCity = config?.store.jurisdiction.city ?? null
  const embeddedLaw = config?.law_pack ?? null

  useEffect(() => {
    if (embeddedLaw) {
      setLawPack(embeddedLaw)
      setLawError(null)
      return
    }
    if (!lawState) return
    let live = true
    api
      .resolveLaw({ state: lawState, city: lawCity })
      .then((p) => {
        if (!live) return
        setLawPack(p)
        setLawError(null)
      })
      .catch((e: Error) => live && setLawError(e.message))
    return () => {
      live = false
    }
  }, [embeddedLaw, lawState, lawCity])

  // Errors (e.g. a locality template not on the server yet) surface in the Store menu.
  const switchStore = useCallback(async (template: string) => {
    const cfg = await createStore(template)
    setResult(null)
    setSolve({ status: 'idle' })
    setOpenGap(null)
    setCallouts([])
    setReadiness(null)
    setConfig(cfg)
  }, [])

  useEffect(() => {
    loadOrCreateStoreOnce()
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

  const setRuleStatus = useCallback(
    async (constraintId: string, status: 'confirmed' | 'rejected') => {
      if (!storeId) return
      try {
        // Full replace on the freshest config so a concurrent chat edit isn't overwritten.
        const cur = await api.getConfig(storeId)
        const next = {
          ...cur,
          constraints: (cur.constraints ?? []).map((c) => (c.id === constraintId ? { ...c, status } : c)),
        }
        setConfig(await api.putConfig(storeId, next))
        void refreshReadiness(storeId)
      } catch (e) {
        setReadinessError(`Couldn't save the rule: ${(e as Error).message}`)
      }
    },
    [storeId, refreshReadiness],
  )

  const runSolve = useCallback(async () => {
    if (!storeId) return
    setSolve({ status: 'running', startedAt: Date.now() })
    setTab('schedule')
    try {
      setResult(await api.solve(storeId))
      setOpenGap(null)
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
        <span className="ml-auto" />
        {apiMode === 'mock' && (
          <span
            className="rounded border border-amber-300/60 bg-amber-300/15 px-2 py-0.5 text-xs font-semibold text-amber-200"
            title="Data comes from the in-browser mock API, not the solver. Open with ?api=live to use the real server."
          >
            Mock API
          </span>
        )}
        <StoreMenu onNew={switchStore} />
      </header>

      <div
        className="grid min-h-0"
        style={{ gridTemplateColumns: `${chatOpen ? 'minmax(320px,30%)' : '3rem'} minmax(0,1fr) ${railOpen ? '19rem' : '3rem'}` }}
      >
        {!chatOpen && (
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            aria-expanded={false}
            className="flex flex-col items-center gap-2 border-r border-rule bg-paper py-3 text-sm font-semibold text-ink-2 hover:text-ink"
          >
            <span className="[writing-mode:vertical-rl]">Chat</span>
          </button>
        )}
        <div className={chatOpen ? 'contents' : 'hidden'}>
          <ChatPane
            key={config.store.id}
            sector={config.store.sector}
            api={api}
            storeId={config.store.id}
            mode="onboard"
            onConfigChanged={() => void onConfigChanged()}
            onScheduleChanged={() => void refreshSchedule(config.store.id)}
            onHide={() => setChatOpen(false)}
          />
        </div>

        <main className="relative flex min-h-0 min-w-0 flex-col overflow-hidden bg-panel">
          <nav className="flex gap-1 border-b border-rule px-3" role="tablist" aria-label="Views">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                disabled={!t.ready}
                title={t.ready ? undefined : 'Not built yet'}
                onClick={() => {
                  setTab(t.id)
                  // These views need the width; the chat is one click away.
                  if (t.id === 'fix' || t.id === 'receipt' || t.id === 'store') setChatOpen(false)
                }}
                className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-semibold ${
                  tab === t.id ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
                } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-muted`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          {tab === 'schedule' && (
            <ScheduleTab
              config={config}
              result={result}
              solve={solve}
              onSolve={() => void runSolve()}
              onGapClick={setOpenGap}
              callouts={callouts}
              onDayClick={(d) => {
                setCoverageDay(d)
                setTab('coverage')
              }}
            />
          )}
          {tab === 'coverage' && (
            <CoverageTab config={config} result={result} onGapClick={setOpenGap} day={coverageDay} onDayChange={setCoverageDay} />
          )}
          {tab === 'store' && <StoreTab config={config} onOpenRulebook={() => setRailOpen(true)} />}
          {tab === 'receipt' && (
            <ReceiptTab
              api={api}
              config={config}
              result={result}
              lawPack={lawPack}
              onValidated={(validation) => setResult((r) => (r ? { ...r, validation } : r))}
            />
          )}
          {/* Kept mounted so a running outreach survives tab switches. */}
          <div className={tab === 'fix' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <FixTab
              key={config.store.id}
              api={api}
              config={config}
              result={result}
              lawPack={lawPack}
              onCallouts={setCallouts}
              onSchedule={(schedule) => {
                // The API saves each accepted call-in with a fresh validator report; fall back to the state's copy.
                api
                  .latestSchedule(config.store.id)
                  .then(setResult)
                  .catch(() => setResult({ schedule, validation: null }))
              }}
            />
          </div>
          {openGap && result && (
            <GapSheet
              api={api}
              storeId={config.store.id}
              gap={openGap}
              weekStart={result.schedule.week_start}
              config={config}
              lawPack={lawPack}
              onClose={() => setOpenGap(null)}
            />
          )}
        </main>

        <ReadinessRail
          readiness={readiness}
          error={readinessError}
          solve={solve}
          onSolve={() => void runSolve()}
          open={railOpen}
          onToggle={() => setRailOpen((o) => !o)}
          roles={config.roles}
          onEquipment={async (roleId, decision) => {
            try {
              setConfig(await api.equipmentRole(config.store.id, roleId, decision))
              void refreshReadiness(config.store.id)
            } catch (e) {
              setReadinessError(`Couldn't save: ${(e as Error).message}`)
            }
          }}
        >
          <Rulebook config={config} lawPack={lawPack} lawError={lawError} onSetStatus={setRuleStatus} />
        </ReadinessRail>
      </div>
    </div>
  )
}
