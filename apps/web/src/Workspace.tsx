import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { apiMode } from './api'
import { ApiError } from './api/client'
import { useApi } from './api/context'
import type { Kickoff, Readiness, SolveResponse } from './api/protocol'
import type { Gap, LawPack, StoreConfig } from './contracts'
import { ChatPane } from './components/ChatPane'
import { CoverageTab } from './components/CoverageTab'
import { FixTab } from './components/FixTab'
import { GapSheet } from './components/GapSheet'
import { EquipmentReview } from './components/EquipmentReview'
import { Rulebook } from './components/Rulebook'
import { ScheduleTab } from './components/ScheduleTab'
import { SetupSteps } from './components/SetupSteps'
import { WorkplaceMenu } from './components/WorkplaceMenu'
import { StoreTab } from './components/StoreTab'
import { ReceiptTab } from './components/ReceiptTab'
import type { SolveState } from './components/SolveButton'
import { fmtDayDate } from './lib/format'
import { ruleNames as makeRuleNames } from './lib/ruleNames'
import { useSolveProgress } from './lib/useSolveProgress'
import { placeLabel, rememberStore } from './lib/stores'

type Tab = 'schedule' | 'callouts' | 'team' | 'compliance'
const TABS: { id: Tab; label: string }[] = [
  { id: 'schedule', label: 'Schedule' },
  { id: 'callouts', label: 'Call-outs' },
  { id: 'team', label: 'Team & rules' },
  { id: 'compliance', label: 'Compliance' },
]

/** `/w/:id`: the workspace for one workplace (chat, schedule, rulebook). Keyed by id, so switching resets it. */
export function Workspace({ storeId: id }: { storeId: string }) {
  const api = useApi()
  const [config, setConfig] = useState<StoreConfig | null>(null)
  const [loadError, setLoadError] = useState<{ notFound: boolean; message: string } | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [readinessError, setReadinessError] = useState<string | null>(null)
  const [result, setResult] = useState<SolveResponse | null>(null)
  const [solve, setSolve] = useState<SolveState>({ status: 'idle' })
  const [tab, setTab] = useState<Tab>('schedule')
  const [scheduleView, setScheduleView] = useState<'week' | 'coverage'>('week')
  const rulesRef = useRef<HTMLElement>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const chatBox = useRef<HTMLDivElement>(null)
  const openChat = useCallback(() => {
    setChatOpen(true)
    setTimeout(() => chatBox.current?.querySelector<HTMLInputElement>('input[aria-label="Message"]')?.focus())
  }, [])
  // B4: setup mode until a schedule exists (GET /schedule answered), then workspace mode.
  const [scheduleChecked, setScheduleChecked] = useState(false)
  const [openGap, setOpenGap] = useState<Gap | null>(null)
  const [coverageDay, setCoverageDay] = useState(0)
  const [callouts, setCallouts] = useState<{ employee_id: string; day: number }[]>([])
  const [lawPack, setLawPack] = useState<LawPack | null>(null)
  const [lawError, setLawError] = useState<string | null>(null)
  const storeId = config?.store.id
  const coverageSoFar = useSolveProgress(api, storeId, solve.status === 'running')
  const lawState = config?.store.jurisdiction.state
  const lawCity = config?.store.jurisdiction.city ?? null
  const embeddedLaw = config?.law_pack ?? null
  const ruleNames = useMemo(() => (config ? makeRuleNames(config, lawPack?.rules) : undefined), [config, lawPack])

  // B7: a generated business arrives with its kickoff in the navigation state. Take it once and clear it, so a
  // reload doesn't send it again.
  const loc = useLocation()
  const navigate = useNavigate()
  const [kickoff] = useState<Kickoff | undefined>(() => (loc.state as { kickoff?: Kickoff } | null)?.kickoff)
  useEffect(() => {
    if (kickoff) navigate(loc.pathname, { replace: true, state: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  }, [])
  const [generated, setGenerated] = useState(!!kickoff)
  useEffect(() => {
    if (kickoff) return
    let live = true
    api
      .workplaces()
      .then(({ workplaces }) => {
        if (live) setGenerated(workplaces.some((w) => w.id === id && w.sample_of === 'generated'))
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [api, id, kickoff])

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
  }, [api, embeddedLaw, lawState, lawCity])

  useEffect(() => {
    let live = true
    api
      .getConfig(id)
      .then((cfg) => {
        if (!live) return
        setConfig(cfg)
        rememberStore(cfg.store.id)
      })
      .catch((e: Error) => live && setLoadError({ notFound: e instanceof ApiError && e.status === 404, message: e.message }))
    return () => {
      live = false
    }
  }, [api, id])

  const refreshReadiness = useCallback(
    async (id: string) => {
      try {
        setReadiness(await api.readiness(id))
        setReadinessError(null)
      } catch (e) {
        setReadinessError((e as Error).message)
      }
    },
    [api],
  )

  const refreshSchedule = useCallback(
    async (id: string) => {
      try {
        setResult(await api.latestSchedule(id))
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) setSolve({ status: 'error', message: (e as Error).message })
      } finally {
        setScheduleChecked(true)
      }
    },
    [api],
  )

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
      setLoadError({ notFound: false, message: (e as Error).message })
    }
    void refreshReadiness(storeId)
  }, [api, storeId, refreshReadiness])

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
    [api, storeId, refreshReadiness],
  )

  const runSolve = useCallback(async () => {
    if (!storeId) return
    setSolve({ status: 'running', startedAt: Date.now() })
    setTab('schedule')
    try {
      setResult(await api.solve(storeId))
      setOpenGap(null)
      setSolve({ status: 'idle' })
    } catch (e) {
      setSolve({ status: 'error', message: (e as Error).message })
    }
  }, [api, storeId])

  if (loadError && !config) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        {loadError.notFound ? (
          <div className="max-w-md">
            <h1 className="text-xl font-semibold">Workplace not found</h1>
            <p className="mt-2 text-ink-2">It may have been removed, or it belongs to a different account.</p>
            <Link to="/workplaces" className="mt-4 inline-block rounded-md bg-ink px-4 py-2 font-semibold text-white">
              My workplaces
            </Link>
          </div>
        ) : (
          <div className="max-w-md">
            <h1 className="text-xl font-semibold">Can't reach the Shiftwright server</h1>
            <p className="mt-2 text-ink-2">{loadError.message}</p>
            {import.meta.env.DEV && (
              <p className="mt-2 text-sm text-muted">
                Start the API on port 8000, or open this page with <code>?api=mock</code> to use the built-in mock.
              </p>
            )}
            <button type="button" className="mt-4 rounded-md bg-ink px-4 py-2 font-semibold text-white" onClick={() => location.reload()}>
              Try again
            </button>
          </div>
        )}
      </div>
    )
  }
  if (!config) {
    return <div className="flex h-full items-center justify-center text-muted">Loading workplace…</div>
  }

  const week = fmtDayDate(config.store.week_start, 0)
  const end = fmtDayDate(config.store.week_start, 6)
  const juris = config.store.jurisdiction

  const setup = !result
  const onEquipment = async (roleId: string, decision: 'confirm' | 'reject') => {
    try {
      setConfig(await api.equipmentRole(config.store.id, roleId, decision))
      void refreshReadiness(config.store.id)
    } catch (e) {
      setReadinessError(`Couldn't save: ${(e as Error).message}`)
    }
  }

  const pendingEquipment = readiness?.checks.find((c) => c.id === 'equipment_roles')

  const workspaceMain = (
    <main className="relative flex min-h-0 min-w-0 flex-col overflow-hidden bg-panel">
      <nav className="flex gap-1 border-b border-rule px-3" role="tablist" aria-label="Views">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-semibold ${
              tab === t.id ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
        <span className="ml-auto self-center" />
        <button
          type="button"
          onClick={() => setChatOpen((o) => !o)}
          aria-expanded={chatOpen}
          className="self-center rounded-full border border-ink/25 bg-panel px-3 py-1 text-sm font-semibold hover:border-ink"
        >
          Ask Shiftwright
        </button>
      </nav>
      {tab === 'schedule' && (
        <>
          <div className="flex items-center gap-1 border-b border-rule-soft px-3 py-1.5 text-sm" role="group" aria-label="Schedule view">
            {(
              [
                ['week', 'Week'],
                ['coverage', 'Coverage by hour'],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={scheduleView === v}
                onClick={() => setScheduleView(v)}
                className={`rounded px-2.5 py-1 font-medium ${scheduleView === v ? 'bg-ink text-white' : 'text-ink-2 hover:bg-paper'}`}
              >
                {label}
              </button>
            ))}
          </div>
          {scheduleView === 'week' ? (
            <ScheduleTab
              config={config}
              result={result}
              solve={solve}
              onSolve={() => void runSolve()}
              onGapClick={setOpenGap}
              callouts={callouts}
              lawRules={lawPack?.rules}
              onOpenChat={openChat}
              coveragePct={coverageSoFar}
              onDayClick={(d) => {
                setCoverageDay(d)
                setScheduleView('coverage')
              }}
            />
          ) : (
            <CoverageTab config={config} result={result} onGapClick={setOpenGap} day={coverageDay} onDayChange={setCoverageDay} />
          )}
        </>
      )}
      {tab === 'team' && (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <StoreTab config={config} onOpenRulebook={() => rulesRef.current?.scrollIntoView?.({ behavior: 'smooth' })} />
          </div>
          <aside ref={rulesRef} className="w-80 shrink-0 overflow-y-auto border-l border-rule px-4 py-3" aria-label="Rules">
            <h2 className="mb-2 font-semibold">Rules</h2>
            {readinessError && <p className="mb-2 text-xs text-gap">{readinessError}</p>}
            <div className="mb-3">
              <EquipmentReview check={pendingEquipment} roles={config.roles} onDecide={onEquipment} />
            </div>
            <Rulebook config={config} lawPack={lawPack} lawError={lawError} onSetStatus={setRuleStatus} />
          </aside>
        </div>
      )}
      {tab === 'compliance' && (
        <ReceiptTab
          api={api}
          config={config}
          result={result}
          lawPack={lawPack}
          onValidated={(validation) => setResult((r) => (r ? { ...r, validation } : r))}
        />
      )}
      {/* Kept mounted so a running outreach survives tab switches. */}
      <div className={tab === 'callouts' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
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
  )

  return (
    <div className="grid h-full grid-rows-[auto_1fr]">
      <header className="flex items-center gap-4 border-b border-ink bg-ink px-4 py-2 text-white">
        <span className="font-semibold">{config.store.name}</span>
        <span className="text-white/70">{placeLabel(juris.city, juris.state)}</span>
        <span className="text-white/70">
          Week of {week.date} to {end.date}
        </span>
        <span className="ml-auto" />
        {import.meta.env.DEV && apiMode === 'mock' && (
          <span
            className="rounded border border-amber-300/60 bg-amber-300/15 px-2 py-0.5 text-xs font-semibold text-amber-200"
            title="Data comes from the in-browser mock API, not the solver. Open with ?api=live to use the real server."
          >
            Mock API
          </span>
        )}
        <WorkplaceMenu currentId={config.store.id} />
      </header>

      {/* The chat keeps its place in this tree in both modes, so the conversation survives the first build. */}
      <div
        className="relative grid min-h-0"
        style={{ gridTemplateColumns: !scheduleChecked ? '1fr' : setup ? '17rem minmax(0,1fr)' : 'minmax(0,1fr)' }}
      >
        {!scheduleChecked ? (
          <div className="flex items-center justify-center text-muted">Loading workplace…</div>
        ) : setup ? (
          <SetupSteps
            readiness={readiness}
            error={readinessError}
            solve={solve}
            onBuild={() => void runSolve()}
            roles={config.roles}
            onEquipment={onEquipment}
            plain={ruleNames?.plain}
            place={placeLabel(juris.city, juris.state)}
            coveragePct={coverageSoFar}
          />
        ) : (
          workspaceMain
        )}
        <div
          className={
            !scheduleChecked
              ? 'hidden'
              : setup
                ? 'flex min-h-0 justify-center bg-paper'
                : chatOpen
                  ? 'absolute inset-y-0 right-0 z-30 flex w-[28rem] max-w-full flex-col border-l border-rule bg-paper shadow-2xl'
                  : 'hidden'
          }
        >
          <div ref={chatBox} className={`grid min-h-0 w-full ${setup ? 'max-w-3xl grid-rows-[minmax(0,1fr)]' : 'flex-1 grid-rows-[auto_minmax(0,1fr)]'}`}>
            {!setup && (
              <div className="flex items-center justify-between border-b border-rule bg-panel px-4 py-2">
                <span className="font-semibold">Ask Shiftwright</span>
                <button type="button" onClick={() => setChatOpen(false)} className="text-sm text-muted hover:text-ink">
                  Close
                </button>
              </div>
            )}
            <ChatPane
              key={config.store.id}
              sector={config.store.sector}
              api={api}
              storeId={config.store.id}
              mode={setup ? 'onboard' : 'review'}
              onConfigChanged={() => void onConfigChanged()}
              onScheduleChanged={() => void refreshSchedule(config.store.id)}
              ruleNames={ruleNames}
              kickoff={kickoff}
              autopilotDefault={generated}
              downloadUrl={generated && apiMode !== 'mock' ? api.sampleDataUrl(config.store.id) : undefined}
              onBuild={setup && readiness?.ready && solve.status !== 'running' ? () => void runSolve() : undefined}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
