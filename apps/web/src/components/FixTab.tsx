import { useEffect, useMemo, useRef, useState } from 'react'
import type { Api, Callout } from '../api/client'
import { ApiError } from '../api/client'
import { apiMode } from '../api'
import type { OutreachState, SolveResponse } from '../api/protocol'
import type { FixAction, FixPlan, InboundMessage, LawPack, LawRule, OutboundMessage, Schedule, StoreConfig } from '../contracts'
import { fmtMoney, fmtPct, fmtRange, fmtTime, WEEKDAY_NAMES } from '../lib/format'
import { roleColors } from '../lib/roles'
import { EmployeeApp } from './EmployeeApp'
import { humanizer } from '../lib/humanize'
import { dayCoveragePct } from '../lib/dayCoverage'

type Props = {
  api: Api
  config: StoreConfig
  result: SolveResponse | null
  lawPack: LawPack | null
  /** Outreach accepted someone: show the updated schedule (not re-validated yet). */
  onSchedule: (s: Schedule) => void
  /** Reported call-outs, so the Schedule grid can mark those shifts. */
  onCallouts?: (c: { employee_id: string; day: number }[]) => void
}

// The demo scenarios' call-outs (packages/scenarios/fixtures/demo_scenario*.json): the big-box stores call out
// Saturday 6:04a; Harbor Grill (demo_scenario_restaurant.json, sector food) Saturday 3:30p.
const DEMOS = {
  retail: { day: 5, now: 364, ids: ['e034', 'e052', 'e053'], text: 'three call-outs at 6:04a Saturday' },
  food: { day: 5, now: 930, ids: ['e005', 'e028'], text: 'two call-outs at 3:30p Saturday' },
}

const LEVER: Record<FixAction['lever'], string> = {
  call_in: 'Call in',
  extend: 'Extend shift',
  reassign: 'Move role',
  drop_coverage: 'Leave uncovered',
}

type Msg = OutboundMessage | InboundMessage
const isOut = (m: Msg): m is OutboundMessage => 'to_employee_id' in m

export function FixTab({ api, config, result, lawPack, onSchedule, onCallouts }: Props) {
  const storeId = config.store.id
  const DEMO = config.store.sector === 'food' ? DEMOS.food : DEMOS.retail
  const hasDemo = DEMO.ids.every((id) => config.employees.some((e) => e.id === id))
  const [day, setDay] = useState(hasDemo ? DEMO.day : 0)
  const [now, setNow] = useState(hasDemo ? DEMO.now : 360)
  const [picked, setPicked] = useState<string[]>(hasDemo ? DEMO.ids : [])
  const [plan, setPlan] = useState<FixPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ status?: number; message: string } | null>(null)
  const [outreach, setOutreach] = useState<OutreachState | null>(null)
  const [phoneOf, setPhoneOf] = useState<string | null>(null)
  const emp = useMemo(() => new Map(config.employees.map((e) => [e.id, e])), [config.employees])
  const roleName = useMemo(() => new Map(config.roles.map((r) => [r.id, r.name])), [config.roles])
  const colors = useMemo(() => roleColors(config.roles), [config.roles])
  const byPhone = (p: string) => config.employees.find((e) => e.phone.replace(/\D/g, '').slice(-10) === p.replace(/\D/g, '').slice(-10))

  const dayShifts = useMemo(
    () => (result?.schedule.shifts ?? []).filter((s) => s.day === day).sort((a, b) => a.start - b.start),
    [result, day],
  )

  // Only people actually working that day can call out (the demo prefill may not match a mock schedule).
  const working = new Set(dayShifts.map((s) => s.employee_id))
  const chosen = picked.filter((id) => working.has(id))

  const [sentCallouts, setSentCallouts] = useState<string[]>([])
  const [planBase, setPlanBase] = useState<Schedule | null>(null)
  const findCoverage = async () => {
    setSentCallouts(chosen)
    setPlanBase(result?.schedule ?? null)
    onCallouts?.(chosen.map((id) => ({ employee_id: id, day })))
    setBusy(true)
    setError(null)
    setPlan(null)
    setOutreach(null)
    try {
      const p = await api.fix(storeId, { callouts: chosen.map((id) => ({ employee_id: id, day, reported_at: now })), day, now })
      setPlan(p)
    } catch (e) {
      setError({ status: e instanceof ApiError ? e.status : undefined, message: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  // Live outreach: SSE snapshots, falling back to polling GET /outreach every 2 s.
  const abortRef = useRef<AbortController | null>(null)
  const lastAccepted = useRef(0)
  const watch = (initial: OutreachState) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setOutreach(initial)
    const apply = (st: OutreachState) => {
      if (ctrl.signal.aborted) return
      setOutreach(st)
      if (st.schedule && st.accepted_employee_ids.length !== lastAccepted.current) {
        lastAccepted.current = st.accepted_employee_ids.length
        onSchedule(st.schedule)
      }
    }
    const poll = async () => {
      while (!ctrl.signal.aborted) {
        try {
          const st = await api.outreach(storeId)
          apply(st)
          if (st.status !== 'texting') return
        } catch {
          /* keep polling */
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    }
    api
      .outreachStream(storeId, apply, ctrl.signal)
      .then(async () => {
        // The stream ends after a non-texting snapshot; one GET makes sure we have the final state.
        if (!ctrl.signal.aborted) apply(await api.outreach(storeId))
      })
      .catch(() => {
        if (!ctrl.signal.aborted) void poll()
      })
  }
  useEffect(() => () => abortRef.current?.abort(), [])

  const startTexting = async () => {
    if (!plan?.plan_id) return
    setError(null)
    lastAccepted.current = 0
    try {
      const st = await api.outreachStart(storeId, plan.plan_id)
      // v1.5: starting saves the plan's no-consent changes (call-outs removed, actions applied).
      if (st.schedule) onSchedule(st.schedule)
      watch(st)
    } catch (e) {
      setError({ status: e instanceof ApiError ? e.status : undefined, message: (e as Error).message })
    }
  }

  const [applied, setApplied] = useState<string | null>(null)
  const applyOnly = async () => {
    if (!plan?.plan_id) return
    setApplied('Applying…')
    try {
      const r = await api.fixApply(storeId, plan.plan_id)
      onSchedule(r.schedule)
      setApplied('Applied to the schedule. Nobody was texted.')
    } catch (e) {
      setApplied(null)
      setError({ status: e instanceof ApiError ? e.status : undefined, message: (e as Error).message })
    }
  }

  // Call-outs that arrive as messages (employee page or a text): the API already planned coverage and
  // started offers. Pick them up here so the manager watches it live.
  const [incoming, setIncoming] = useState<Callout | null>(null)
  const seenCallout = useRef<string | null>(null)
  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const r = await api.callout(storeId)
        const co = r.callout
        if (!alive || !co || co.id === seenCallout.current) return
        const first = seenCallout.current === null
        seenCallout.current = co.id
        if (first && Date.now() - new Date(co.at).getTime() > 30 * 60_000) return // old news on load
        setIncoming(co)
        if (!r.plan || co.day === undefined) return
        setDay(co.day)
        setNow(co.now ?? 0)
        setPicked([co.employee_id])
        setSentCallouts([co.employee_id])
        setPlanBase(result?.schedule ?? null)
        onCallouts?.([{ employee_id: co.employee_id, day: co.day }])
        setPlan(r.plan)
        setError(null)
        const st = await api.outreach(storeId)
        if (st.schedule) onSchedule(st.schedule)
        lastAccepted.current = 0
        if (st.plan_id === co.plan_id) watch(st)
      } catch {
        /* older API without /callout, or offline: the manual flow still works */
      }
    }
    void check()
    const t = setInterval(() => void check(), 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId])

  const stop = async () => {
    try {
      setOutreach(await api.outreachCancel(storeId))
    } catch (e) {
      setError({ message: (e as Error).message })
    }
  }

  if (!result) {
    return (
      <div className="p-10">
        <h2 className="text-xl font-semibold">Build the schedule first</h2>
        <p className="mt-2 text-ink-2">Call-outs are fixed against this week's schedule. Build it from the Schedule tab.</p>
      </div>
    )
  }

  const callouts = new Set(picked)
  const status = outreach?.status ?? 'idle'
  const liveCoverage = outreach?.schedule?.metrics?.coverage_pct
  const dayCov = plan
    ? {
        before: dayCoveragePct(config, planBase, day),
        afterCallouts: dayCoveragePct(config, planBase, day, sentCallouts),
        best: dayCoveragePct(config, plan.schedule_if_all_accept, day),
        worst: dayCoveragePct(config, plan.schedule_if_none_accept, day),
        live: outreach?.schedule ? dayCoveragePct(config, outreach.schedule, day) : null,
      }
    : null

  return (
    <div className="flex min-h-0 flex-1">
      <div className={`min-h-0 flex-1 overflow-y-auto ${phoneOf ? 'pl-[380px]' : ''}`}>
        <TextAsEmployee config={config} schedule={result.schedule} onOpen={setPhoneOf} />
        {incoming && (
          <section className="border-b border-rule bg-pine-wash px-4 py-3 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <span className="font-semibold">
                  {incoming.employee_name} messaged at {new Date(incoming.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}:
                </span>{' '}
                <span className="italic">“{incoming.body}”</span>
                <div className="mt-1 text-ink-2">
                  {incoming.status === 'not_a_callout'
                    ? 'Not a call-out, so nothing changed.'
                    : incoming.shift
                      ? `Read as a call-out for ${incoming.shift.label}. ${incoming.note}`
                      : incoming.note}
                  {incoming.status === 'covering' && incoming.texting && ' You can stop the offers below.'}
                </div>
              </div>
              <button type="button" className="shrink-0 text-xs text-muted hover:text-ink" onClick={() => setIncoming(null)} aria-label="Dismiss">
                ×
              </button>
            </div>
          </section>
        )}
        {/* 1. Report call-outs (frozen to a summary once there's a plan) */}
        {plan ? (
          <section className="flex items-center gap-3 border-b border-rule px-4 py-3">
            <span className="text-sm">
              <span className="font-semibold">
                Called out {WEEKDAY_NAMES[day]} at {fmtTime(now)}:
              </span>{' '}
              {sentCallouts.map((id) => emp.get(id)?.name ?? id).join(', ')}
            </span>
            <button
              type="button"
              disabled={status === 'texting'}
              onClick={() => {
                setPlan(null)
                setOutreach(null)
                abortRef.current?.abort()
              }}
              title={status === 'texting' ? 'Stop texting first' : undefined}
              className="ml-auto rounded-md border border-rule px-3 py-1 text-sm font-semibold hover:border-ink disabled:opacity-50"
            >
              Report different call-outs
            </button>
          </section>
        ) : (
          <section className="border-b border-rule px-4 py-3">
            <div className="flex flex-wrap items-end gap-3">
              <h2 className="mr-2 text-lg font-semibold">Who called out?</h2>
              <label className="text-sm">
                <span className="block text-xs text-muted">Day</span>
                <select
                  className="rounded-md border border-rule px-2 py-1"
                  value={day}
                  onChange={(e) => {
                    setDay(Number(e.target.value))
                    setPicked([])
                  }}
                >
                  {WEEKDAY_NAMES.map((w, d) => (
                    <option key={w} value={d}>
                      {w}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                <span className="block text-xs text-muted">Time now</span>
                <input
                  type="time"
                  className="rounded-md border border-rule px-2 py-1"
                  value={`${String(Math.floor(now / 60)).padStart(2, '0')}:${String(now % 60).padStart(2, '0')}`}
                  onChange={(e) => {
                    const [h, m] = e.target.value.split(':').map(Number)
                    setNow((h || 0) * 60 + (m || 0))
                  }}
                />
              </label>
              <button
                type="button"
                disabled={chosen.length === 0 || busy || status === 'texting'}
                onClick={() => void findCoverage()}
                className="ml-auto rounded-md bg-pine px-4 py-2 font-semibold text-white hover:bg-pine-dark disabled:opacity-50"
              >
                {busy ? 'Finding coverage…' : `Find coverage for ${chosen.length || 'no one'}`}
              </button>
            </div>
            <p className="mt-2 text-xs text-muted">
              {dayShifts.length} people work {WEEKDAY_NAMES[day]}. Tap everyone who called out.
              {hasDemo && day === DEMO.day ? ` Prefilled with the demo: ${DEMO.text}.` : ''}
            </p>
            <div className="mt-2 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
              {dayShifts.map((s) => {
                const on = callouts.has(s.employee_id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setPicked((p) => (on ? p.filter((x) => x !== s.employee_id) : [...p, s.employee_id]))}
                    className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-left text-xs ${
                      on ? 'border-gap bg-gap-wash text-gap' : 'border-rule hover:border-ink'
                    }`}
                  >
                    <span className="inline-block h-3 w-1 rounded-sm" style={{ background: colors.get(s.segments[0]?.role_id ?? '') }} />
                    <span className="font-semibold">{emp.get(s.employee_id)?.name ?? s.employee_id}</span>
                    <span className={on ? '' : 'text-muted'}>{fmtRange(s.start, s.end)}</span>
                  </button>
                )
              })}
            </div>
          </section>
        )}

        {error && (
          <div className="m-4 rounded-md border border-gap/30 bg-gap-wash px-4 py-3 text-sm">
            {error.status === 503 ? (
              <>
                <p className="font-semibold text-gap">The call-out fixer isn't on this server yet.</p>
                <p className="mt-1 text-ink-2">
                  The engine's <code>fix_day</code> hasn't landed, so the API can't plan coverage. ({error.message})
                </p>
                {import.meta.env.DEV && apiMode === 'live' && (
                  <p className="mt-1 text-ink-2">
                    To preview the flow, open the app with{' '}
                    <a className="font-semibold text-pine-dark underline" href="?api=mock">
                      ?api=mock
                    </a>{' '}
                    (built-in mock; numbers come from the mock, not the solver).
                  </p>
                )}
              </>
            ) : error.status === 409 ? (
              <p className="text-gap">{error.message}</p>
            ) : (
              <p className="text-gap">Couldn't plan coverage: {error.message}</p>
            )}
          </div>
        )}

        {plan && <PlanView plan={plan} config={config} roleName={roleName} outreach={outreach} lawPack={lawPack} dayCov={dayCov} day={day} />}
      </div>

      {phoneOf && (
        <div className="fixed bottom-4 left-4 z-50">
          <div className="flex flex-col items-end gap-2">
            <div className="flex gap-3 rounded-full bg-ink px-3 py-1 text-sm text-white shadow">
              {apiMode === 'live' && (
                <a
                  className="underline"
                  href={`?employee=${encodeURIComponent(phoneOf)}&store=${encodeURIComponent(storeId)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in a new window
                </a>
              )}
              <button type="button" onClick={() => setPhoneOf(null)} className="font-semibold">
                Close
              </button>
            </div>
            <div className="h-[min(760px,80vh)] w-[360px] overflow-hidden rounded-[2rem] border-8 border-ink bg-paper shadow-2xl">
              <EmployeeApp employeeId={phoneOf} storeId={storeId} />
            </div>
          </div>
        </div>
      )}
      {plan && (
        <Phone
          plan={plan}
          outreach={outreach}
          liveCoverage={liveCoverage}
          dayCov={dayCov}
          dayName={WEEKDAY_FULL[day]}
          onStart={() => void startTexting()}
          onApplyOnly={() => void applyOnly()}
          applied={applied}
          onStop={() => void stop()}
          nameOf={(id) => emp.get(id)?.name ?? id}
          onOpenPhone={setPhoneOf}
          phoneFor={(id) => emp.get(id)?.phone ?? ''}
          byPhone={byPhone}
          onReply={async (phone, body) => {
            try {
              await api.mockReply(phone, body)
            } catch (e) {
              setError({ message: `Reply failed: ${(e as Error).message}` })
            }
          }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ plan

function PlanView({
  plan,
  config,
  roleName,
  outreach,
  lawPack,
  dayCov,
  day,
}: {
  plan: FixPlan
  config: StoreConfig
  roleName: Map<string, string>
  outreach: OutreachState | null
  lawPack: LawPack | null
  dayCov: DayCov | null
  day: number
}) {
  const lawById = new Map((lawPack?.rules ?? []).map((r) => [r.id, r]))
  const hasScheduleLaw = (lawPack?.rules ?? []).some((r) => r.type === 'predictive_scheduling')
  const emp = new Map(config.employees.map((e) => [e.id, e]))
  const texted = new Set((outreach?.messages ?? []).filter(isOut).map((m) => m.to_employee_id))
  const accepted = new Set(outreach?.accepted_employee_ids ?? [])
  const declined = new Set(
    (outreach?.messages ?? [])
      .filter((m): m is InboundMessage => !isOut(m) && m.interpreted_as === 'decline')
      .map((m) => config.employees.find((e) => e.phone.replace(/\D/g, '').slice(-10) === m.from_phone.replace(/\D/g, '').slice(-10))?.id)
      .filter((x): x is string => !!x),
  )
  const mock = (plan.schedule_if_none_accept?.produced_by ?? '').startsWith('mock')
  const h = humanizer(config)
  const direct = plan.actions.filter((a) => a.lever === 'extend' || a.lever === 'call_in')
  const moves = plan.actions.filter((a) => a.lever === 'reassign')
  const drops = plan.actions.filter((a) => a.lever === 'drop_coverage')

  return (
    <div className="space-y-4 p-4">
      {mock && (
        <p className="rounded-md bg-warn-wash px-3 py-1.5 text-xs font-medium text-warn">
          Mock plan from the in-browser mock, not the engine.
        </p>
      )}
      <div>
        <div className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{WEEKDAY_FULL[day]} coverage</div>
        <div className="grid grid-cols-4 gap-px overflow-hidden rounded-lg border border-rule bg-rule">
          <Big label="Before the call-outs" value={pctOr(dayCov?.before)} tone="text-ink-2" />
          <Big label="After the call-outs" value={pctOr(dayCov?.afterCallouts)} tone="text-gap" />
          <Big label="Plan, if the first choices say yes" value={pctOr(dayCov?.best)} tone="text-pine-dark" />
          <Big label="Plan, if nobody says yes" value={pctOr(dayCov?.worst)} tone="text-ink-2" />
        </div>
        <p className="mt-1 text-[11px] text-muted">
          {WEEKDAY_FULL[day]} only: needed headcount-minutes covered, from the store's demand and each schedule's shifts (same
          definition as the weekly figure). Week: {fmtPct(plan.coverage_before_pct)} after the call-outs →{' '}
          {fmtPct(plan.coverage_after_best_pct)} best / {fmtPct(plan.coverage_after_worst_pct)} if nobody says yes.
        </p>
      </div>

      <ModeBanner plan={plan} outreach={outreach} h={h} lawById={lawById} noScheduleLaw={!!lawPack && !hasScheduleLaw} />

      <section>
        <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted uppercase">Right away (no texts needed)</h3>
        {direct.length === 0 && moves.length === 0 && <p className="text-sm text-muted">Nothing to change on today's shifts.</p>}
        <ul className="space-y-1.5">
          {direct.map((a, i) => (
            <li key={i} className="flex items-start gap-3 rounded-md border border-rule px-3 py-2 text-sm">
              <span className="shrink-0 rounded bg-pine-wash px-1.5 py-0.5 text-xs font-semibold text-pine-dark">{LEVER[a.lever]}</span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">
                  {a.employee_id ? `${emp.get(a.employee_id)?.name ?? a.employee_id}, ` : ''}
                  {a.role_id ? `${roleName.get(a.role_id) ?? a.role_id} ` : ''}
                  {fmtRange(a.start, a.end)}
                </span>
                <PremiumLine action={a} lawById={lawById} />
                <details className="text-xs text-muted">
                  <summary className="cursor-pointer">Details</summary>
                  {h(a.rationale)}
                </details>
              </span>
              <span className="shrink-0 text-right tabular-nums">
                {a.added_cost_dollars ? `+${fmtMoney(a.added_cost_dollars, { cents: true })}` : '—'}
              </span>
            </li>
          ))}
        </ul>
        {moves.length > 0 && (
          <details className="mt-1.5 rounded-md border border-rule px-3 py-2 text-sm">
            <summary className="cursor-pointer">
              <span className="mr-2 rounded bg-pine-wash px-1.5 py-0.5 text-xs font-semibold text-pine-dark">Move role</span>
              {moves.length} role {moves.length === 1 ? 'move' : 'moves'} for {new Set(moves.map((a) => a.employee_id)).size} people already
              on shift, no extra cost
            </summary>
            <ul className="mt-1.5 space-y-0.5 text-xs text-ink-2">
              {moves.map((a, i) => (
                <li key={i}>
                  {a.employee_id ? (emp.get(a.employee_id)?.name ?? a.employee_id) : ''} →{' '}
                  {a.role_id ? (roleName.get(a.role_id) ?? a.role_id) : ''} {fmtRange(a.start, a.end)}
                </li>
              ))}
            </ul>
          </details>
        )}
        {drops.length > 0 && (
          <details className="mt-1.5 rounded-md border border-rule px-3 py-2 text-sm">
            <summary className="cursor-pointer">
              <span className="mr-2 rounded bg-gap-wash px-1.5 py-0.5 text-xs font-semibold text-gap">Still uncovered</span>
              {drops.length} {drops.length === 1 ? 'stretch' : 'stretches'} unless someone says yes
            </summary>
            <ul className="mt-1.5 space-y-0.5 text-xs text-ink-2">
              {[...drops]
                .sort((a, b) => a.start - b.start)
                .map((a, i) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span>
                      {a.role_id ? (roleName.get(a.role_id) ?? a.role_id) : ''} {fmtRange(a.start, a.end)}
                    </span>
                  </li>
                ))}
            </ul>
          </details>
        )}
      </section>

      <section>
        <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted uppercase">
          {plan.outreach_mode === 'group_offer' ? 'Who gets the offer' : 'Who to text, in order'}
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted">
              <th className="py-1 pr-2 text-left font-medium">#</th>
              <th className="py-1 pr-2 text-left font-medium">Person</th>
              <th className="py-1 pr-2 text-left font-medium">Shift offered</th>
              <th className="py-1 pr-2 text-right font-medium">Cost</th>
              <th className="py-1 pr-2 text-right font-medium">Likely yes</th>
              <th className="py-1 text-left font-medium">Premium</th>
            </tr>
          </thead>
          <tbody>
            {plan.outreach_queue.map((c) => {
              const e = emp.get(c.employee_id)
              const waiting = (outreach?.waiting_employee_ids ?? []).includes(c.employee_id)
              const st = accepted.has(c.employee_id)
                ? { label: 'Said yes', cls: 'bg-pine text-white' }
                : declined.has(c.employee_id)
                  ? { label: 'Said no', cls: 'bg-rule text-ink-2' }
                  : outreach?.status === 'texting' && (waiting || outreach.current_rank === c.rank)
                    ? { label: 'Texting…', cls: 'bg-warn-wash text-warn' }
                    : texted.has(c.employee_id)
                      ? { label: outreach?.status === 'texting' ? 'Texted' : 'No reply', cls: 'bg-rule-soft text-ink-2' }
                      : null
              const sh = c.proposed_shift
              return (
                <tr key={c.rank} className="border-t border-rule-soft align-top">
                  <td className="py-1.5 pr-2 font-semibold tabular-nums">{c.rank}</td>
                  <td className="py-1.5 pr-2">
                    <span className="font-medium whitespace-nowrap">{e?.name ?? c.employee_id}</span>
                    {st && <span className={`ml-1.5 rounded px-1 text-[10px] font-semibold whitespace-nowrap ${st.cls}`}>{st.label}</span>}
                    <span className="block text-xs text-muted">{h(c.why)}</span>
                  </td>
                  <td className="py-1.5 pr-2 text-ink-2">
                    <span className="whitespace-nowrap">
                      {[...new Set(sh.segments.map((g) => roleName.get(g.role_id) ?? g.role_id))].join(', ')} {fmtRange(sh.start, sh.end)}
                    </span>
                    {(sh.why ?? []).length > 0 && <span className="block text-xs text-muted">{h(sh.why![0])}</span>}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(c.added_cost_dollars, { cents: true })}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{Math.round(c.est_accept_prob * 100)}%</td>
                  <td className="py-1.5 text-xs">
                    <CandidatePremium
                      dollars={c.premium_pay_dollars ?? 0}
                      ids={c.law_rule_ids ?? []}
                      note={c.premium_note ?? ''}
                      lawById={lawById}
                      h={h}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {plan.outreach_queue.length === 0 && <p className="text-sm text-muted">Nobody to text: the plan covers it without call-ins.</p>}
      </section>
    </div>
  )
}

function lawLabel(r: LawRule | undefined, id: string): string {
  if (!r) return id
  const place =
    r.level === 'city' && r.jurisdiction.city
      ? r.jurisdiction.city.replace(/\b\w/g, (c) => c.toUpperCase())
      : r.level === 'federal'
        ? 'Federal'
        : r.jurisdiction.state
  const kind = r.type === 'predictive_scheduling' ? 'predictability pay' : r.type.replace(/_/g, ' ')
  return `${place} ${kind}`
}

/** Premium per action (SEMANTICS #17): the engine's amount and law, or why there is none. Never computed here. */
function PremiumLine({ action: a, lawById }: { action: FixAction; lawById: Map<string, LawRule> }) {
  const ids = a.law_rule_ids ?? []
  const premium = a.premium_pay_dollars ?? 0
  if (premium > 0)
    return (
      <span className="mt-1 flex flex-wrap gap-1">
        {(ids.length ? ids : ['']).map((id) => {
          const r = lawById.get(id)
          return (
            <span key={id} className="rounded bg-warn-wash px-1.5 py-0.5 text-xs font-semibold text-warn" title={r?.summary}>
              +{fmtMoney(premium, { cents: true })} {id ? lawLabel(r, id) : 'premium pay'}
              {r && (
                <a href={r.citation.url} target="_blank" rel="noreferrer" className="ml-1 font-normal underline">
                  source
                </a>
              )}
            </span>
          )
        })}
      </span>
    )
  if (ids.length > 0)
    return (
      <span className="mt-1 block text-xs">
        <span className="rounded bg-pine-wash px-1.5 py-0.5 font-semibold text-pine-dark">No premium</span>{' '}
        <span className="text-muted">{ids.map((id) => lawLabel(lawById.get(id), id)).join(', ')} checked</span>
      </span>
    )
  return null // "no scheduling law here" is said once, in the mode banner
}

function CandidatePremium({
  dollars,
  ids,
  note,
  lawById,
  h,
}: {
  dollars: number
  ids: string[]
  note: string
  lawById: Map<string, LawRule>
  h: (t: string) => string
}) {
  const label = ids.map((id) => lawLabel(lawById.get(id), id)).join(', ')
  if (dollars > 0)
    return (
      <span className="rounded bg-warn-wash px-1.5 py-0.5 font-semibold whitespace-nowrap text-warn" title={note ? h(note) : undefined}>
        +{fmtMoney(dollars, { cents: true })} {label || 'premium'}
      </span>
    )
  if (ids.length > 0)
    return (
      <span title={note ? h(note) : undefined}>
        <span className="rounded bg-pine-wash px-1.5 py-0.5 font-semibold whitespace-nowrap text-pine-dark">No premium</span>
        <span className="mt-0.5 block text-muted">{shortExempt(note) || `${label} checked`}</span>
      </span>
    )
  return <span className="text-muted">—</span>
}

/** "No predictability pay: voluntary call-in accepted in writing; …" → "Voluntary call-in accepted in writing". */
function shortExempt(note: string): string {
  const m = note.match(/^(?:No [^:]+:\s*)?([^;.]+)/)
  if (!m) return ''
  const t = m[1].trim()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** How offers go out (one at a time vs group message) and whether predictability pay is owed. From plan + state only. */
function ModeBanner({
  plan,
  outreach,
  h,
  lawById,
  noScheduleLaw,
}: {
  plan: FixPlan
  outreach: OutreachState | null
  h: (t: string) => string
  lawById: Map<string, LawRule>
  noScheduleLaw: boolean
}) {
  const mode = outreach?.mode ?? plan.outreach_mode ?? 'one_to_one'
  const prem = outreach?.premium
  const total = (prem?.by_employee ?? [])
    .filter((b) => (outreach?.accepted_employee_ids ?? []).includes(b.employee_id))
    .reduce((c, b) => c + b.premium_pay_dollars, 0)
  const ids = prem?.law_rule_ids ?? plan.outreach_queue.flatMap((c) => c.law_rule_ids ?? [])
  const label = [...new Set(ids)].map((id) => lawLabel(lawById.get(id), id)).join(', ')
  return (
    <div className="rounded-lg border border-rule bg-paper px-3 py-2 text-sm">
      <div className="font-semibold">
        {mode === 'group_offer'
          ? 'Group offer: several people get the same text; the first yes gets the shift.'
          : 'Texts go out one at a time, best match first.'}
        {outreach && (outreach.wave ?? 0) > 0 && <span className="ml-2 font-normal text-muted">Round {outreach.wave}</span>}
      </div>
      {prem ? (
        <div className={`mt-0.5 ${prem.status === 'owed' ? 'text-warn' : 'text-ink-2'}`}>
          <span className="font-semibold">
            {prem.status === 'owed'
              ? `Premium owed${total ? `: ${fmtMoney(total, { cents: true })} so far` : ''}`
              : prem.status === 'exempt'
                ? 'No premium owed'
                : 'No scheduling-law premium here'}
            {label ? ` · ${label}` : ''}.
          </span>{' '}
          <NoteWithSource text={h(prem.note)} />
        </div>
      ) : label ? (
        <p className="mt-0.5 text-ink-2">Premiums below come from {label}; the outreach confirms whether they're owed.</p>
      ) : noScheduleLaw ? (
        <p className="mt-0.5 text-ink-2">No predictive-scheduling law in this location's labor rules, so changes today carry no premium.</p>
      ) : null}
    </div>
  )
}

/** Plain first part of a note, with any quoted source text folded away. */
function NoteWithSource({ text }: { text: string }) {
  const i = text.search(/\s(Exempt:|")/)
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}{' '}
      <details className="inline">
        <summary className="inline cursor-pointer text-xs text-pine-dark underline">source text</summary>
        <span className="block text-xs text-muted">{text.slice(i + 1)}</span>
      </details>
    </>
  )
}

type DayCov = { before: number | null; afterCallouts: number | null; best: number | null; worst: number | null; live: number | null }
const WEEKDAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const pctOr = (v: number | null | undefined) => (v == null ? '—' : fmtPct(v))

function Big({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="bg-panel px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  )
}

// ------------------------------------------------------------------ phone

function useTween(target: number | undefined) {
  const [v, setV] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    if (target == null) return
    const start = from.current ?? target
    const t0 = performance.now()
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 900)
      const val = start + (target - start) * (1 - (1 - k) ** 3)
      setV(val)
      from.current = val
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target])
  return v
}

function Phone({
  plan,
  outreach,
  liveCoverage,
  dayCov,
  dayName,
  onStart,
  onApplyOnly,
  applied,
  onStop,
  onReply,
  nameOf,
  byPhone,
  onOpenPhone,
  phoneFor,
}: {
  plan: FixPlan
  outreach: OutreachState | null
  liveCoverage: number | undefined
  dayCov: DayCov | null
  dayName: string
  onStart: () => void
  onApplyOnly: () => void
  applied: string | null
  onStop: () => void
  onReply: (phone: string, body: string) => Promise<void>
  nameOf: (id: string) => string
  onOpenPhone: (employeeId: string) => void
  phoneFor: (employeeId: string) => string
  byPhone: (p: string) => { id: string; name: string } | undefined
}) {
  const status = outreach?.status ?? 'idle'
  const msgs = outreach?.messages ?? []
  const pending = [...msgs].reverse().find(isOut)
  const waitingOnPending = status === 'texting' && pending && pending.outreach_rank === outreach?.current_rank
  // v1.4: group offers wait on several people at once.
  const waiters: { id: string; phone: string }[] =
    status !== 'texting'
      ? []
      : outreach?.waiting_employee_ids?.length
        ? outreach.waiting_employee_ids.map((id) => ({ id, phone: phoneFor(id) })).filter((w) => w.phone)
        : waitingOnPending && pending
          ? [{ id: pending.to_employee_id, phone: pending.to_phone }]
          : []
  // Headline: the day's coverage (live during outreach); the weekly figure is secondary.
  const dayNow = dayCov?.live ?? dayCov?.afterCallouts ?? null
  const shown = useTween(dayNow ?? liveCoverage ?? plan.coverage_before_pct)
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [msgs.length])
  const fmtClock = (iso: string) => {
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? '' : fmtTime(d.getHours() * 60 + d.getMinutes())
  }

  return (
    <aside className="flex w-[21rem] shrink-0 flex-col border-l border-rule bg-paper" aria-label="Outreach">
      <div className="border-b border-rule bg-panel px-4 py-3">
        <div className="flex items-baseline justify-between">
          <span className="text-xs text-muted">{dayNow != null ? `${dayName} coverage` : 'Coverage'}</span>
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${STATUS_CLS[status]}`}>{STATUS_LABEL[status]}</span>
        </div>
        <div className="text-3xl font-semibold tabular-nums">{fmtPct(shown ?? 0)}</div>
        <div className="text-xs text-muted">
          {(outreach?.accepted_employee_ids ?? []).length > 0
            ? `${outreach!.accepted_employee_ids.map(nameOf).join(', ')} said yes`
            : `Best case ${dayCov?.best != null ? fmtPct(dayCov.best) : fmtPct(plan.coverage_after_best_pct)} if the first choices say yes`}
          {dayNow != null && <span className="block">Week {fmtPct(liveCoverage ?? plan.coverage_before_pct)}</span>}
        </div>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {status === 'idle' && msgs.length === 0 && (
          <div className="pt-6 text-center">
            <p className="text-sm text-ink-2">
              Texts go out one at a time, in the order on the left. Each person gets a few minutes before the next is asked.
            </p>
            <p className="mt-1 text-xs text-muted">Phones are simulated in this demo; no real texts are sent.</p>
          </div>
        )}
        {msgs.map((m) => {
          if (isOut(m))
            return (
              <div key={m.id} className="ml-8">
                <div className="mb-0.5 text-right text-[10px] text-muted">
                  To {nameOf(m.to_employee_id)}
                  {m.outreach_rank ? ` · #${m.outreach_rank}` : ''} · {fmtClock(m.sent_at)} ·{' '}
                  <button
                    type="button"
                    onClick={() => onOpenPhone(m.to_employee_id)}
                    className="font-semibold text-pine-dark hover:underline"
                  >
                    Open {nameOf(m.to_employee_id).split(' ')[0]}'s phone
                  </button>
                </div>
                <div className="rounded-2xl rounded-br-sm bg-pine px-3 py-2 text-sm text-white">{m.body}</div>
              </div>
            )
          if (m.from_phone === 'system')
            return (
              <p key={m.id} className="text-center text-xs text-muted">
                {m.body}
              </p>
            )
          const who = byPhone(m.from_phone)
          return (
            <div key={m.id} className="mr-8">
              <div className="mb-0.5 text-[10px] text-muted">
                {who?.name ?? m.from_phone} · {fmtClock(m.received_at)}
                {m.interpreted_as && m.interpreted_as !== 'unknown' ? ` · read as ${m.interpreted_as}` : ''}
              </div>
              <div className="rounded-2xl rounded-bl-sm bg-panel px-3 py-2 text-sm shadow-sm ring-1 ring-rule">{m.body}</div>
            </div>
          )
        })}
        {waitingOnPending && <div className="mr-8 h-7 w-12 animate-pulse rounded-2xl bg-rule" aria-label="Waiting for a reply" />}
      </div>

      <div className="border-t border-rule bg-panel px-3 py-3">
        {status === 'idle' || status === 'exhausted' || status === 'filled' ? (
          <button
            type="button"
            onClick={onStart}
            disabled={!plan.plan_id || plan.outreach_queue.length === 0}
            className={`w-full rounded-md px-4 py-2.5 font-semibold disabled:opacity-50 ${
              status === 'idle' ? 'bg-pine text-white hover:bg-pine-dark' : 'border border-rule text-ink-2 hover:border-ink'
            }`}
          >
            {status === 'idle' ? 'Start texting' : status === 'filled' ? 'Text again from the top' : 'Try the list again'}
          </button>
        ) : (
          <>
            {waiters.map((w) => (
              <div key={w.id} className="mb-2">
                <div className="mb-1 text-xs text-muted">Reply as {nameOf(w.id)}:</div>
                <div className="flex gap-1.5">
                  {[
                    ['Yes', 'Yes, I can come in'],
                    ['No', "No, sorry, can't today"],
                    ['Question', 'What time would I be done?'],
                  ].map(([label, body]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => void onReply(w.phone, body)}
                      className="flex-1 rounded-md border border-rule px-2 py-1 text-sm font-semibold hover:border-ink"
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {waiters.length > 0 && (
              <p className="mb-1 text-[11px] text-muted">Simulated replies; the demo phones also answer on their own.</p>
            )}
            <button type="button" onClick={onStop} className="w-full rounded-md px-3 py-1.5 text-sm text-ink-2 hover:bg-paper">
              Stop texting
            </button>
          </>
        )}
        {status === 'idle' && (
          <div className="mt-1.5 text-center text-xs">
            {applied ? (
              <span className="text-pine-dark">{applied}</span>
            ) : (
              <button type="button" onClick={onApplyOnly} disabled={!plan.plan_id} className="text-ink-2 underline hover:text-ink">
                Just make today's changes, don't text anyone
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}

const STATUS_LABEL: Record<OutreachState['status'], string> = {
  idle: 'Not started',
  texting: 'Texting',
  filled: 'All covered',
  exhausted: 'Stopped',
}
const STATUS_CLS: Record<OutreachState['status'], string> = {
  idle: 'bg-rule-soft text-ink-2',
  texting: 'bg-warn-wash text-warn',
  filled: 'bg-pine text-white',
  exhausted: 'bg-rule text-ink-2',
}

/** "Text as an employee": pick someone and their phone opens beside the manager's view. People working
 *  today (store time) come first, so a call-out has a shift to land on. */
function TextAsEmployee({ config, schedule, onOpen }: { config: StoreConfig; schedule: Schedule; onOpen: (id: string) => void }) {
  const [who, setWho] = useState('')
  const today = useMemo(() => {
    try {
      const wd = new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: config.store.timezone || 'America/Chicago' }).format(new Date())
      return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(wd)
    } catch {
      return (new Date().getDay() + 6) % 7
    }
  }, [config.store.timezone])
  const people = useMemo(() => {
    const working = new Set(schedule.shifts.filter((s) => s.day === today).map((s) => s.employee_id))
    const scheduled = new Set(schedule.shifts.map((s) => s.employee_id))
    return config.employees
      .filter((e) => e.phone && scheduled.has(e.id))
      .map((e) => ({ e, today: working.has(e.id) }))
      .sort((a, b) => Number(b.today) - Number(a.today) || a.e.name.localeCompare(b.e.name))
  }, [config.employees, schedule.shifts, today])
  if (people.length === 0) return null
  return (
    <section className="flex flex-wrap items-center gap-2 border-b border-rule bg-panel px-4 py-2.5 text-sm">
      <span className="font-semibold">Text the store as an employee:</span>
      <select className="rounded-md border border-rule bg-paper px-2 py-1" value={who} onChange={(e) => setWho(e.target.value)} aria-label="Employee">
        <option value="">Pick someone…</option>
        {people.map(({ e, today: t }) => (
          <option key={e.id} value={e.id}>
            {e.name}
            {t ? ` (works ${WEEKDAY_NAMES[today]})` : ''}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!who}
        onClick={() => onOpen(who)}
        className="rounded-md bg-ink px-3 py-1 font-semibold text-white disabled:opacity-40"
      >
        Open their phone
      </button>
      <span className="text-xs text-muted">Type a message like "I'm sick, can't make it today" and watch the fix start here.</span>
    </section>
  )
}
