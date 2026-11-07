// Phone-sized employee view: ?employee=<id>&store=<id> (390×844). Their week and their shift offers.
// Replies go through POST /api/sms/mock-reply (mock messenger only), the same path as a real text.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Callout } from '../api/client'
import { STORE_KEY } from '../lib/stores'
import type { OutreachState } from '../api/protocol'
import type { InboundMessage, OutboundMessage, Schedule, StoreConfig } from '../contracts'
import { fmtDayDate, fmtHours, fmtRange, fmtTime, WEEKDAY_NAMES } from '../lib/format'
import { paidMinutes } from '../lib/compliance'

type Msg = OutboundMessage | InboundMessage
const isOut = (m: Msg): m is OutboundMessage => 'to_employee_id' in m
const digits = (p: string) => p.replace(/\D/g, '').slice(-10)

export function EmployeeApp({ employeeId, storeId: given }: { employeeId: string; storeId?: string }) {
  const storeId = useMemo(() => {
    if (given) return given
    const q = new URLSearchParams(location.search).get('store')
    if (q) return q
    try {
      return localStorage.getItem(STORE_KEY)
    } catch {
      return null
    }
  }, [given])
  const [cfg, setCfg] = useState<StoreConfig | null>(null)
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [outreach, setOutreach] = useState<OutreachState | null>(null)
  const [mockMessenger, setMockMessenger] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!storeId) return
    try {
      const [c, o] = await Promise.all([api.getConfig(storeId), api.outreach(storeId).catch(() => null)])
      setCfg(c)
      setOutreach(o)
      const s = await api.latestSchedule(storeId).catch(() => null)
      setSchedule(o?.schedule ?? s?.schedule ?? null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [storeId])

  useEffect(() => {
    void refresh()
    api
      .health()
      .then((h) => setMockMessenger(h.messenger === 'mock'))
      .catch(() => setMockMessenger(true)) // the in-browser mock has no real phones either
    const t = setInterval(() => void refresh(), 2000)
    return () => clearInterval(t)
  }, [refresh])

  const me = cfg?.employees.find((e) => e.id === employeeId)
  const roleName = (id: string) => cfg?.roles.find((r) => r.id === id)?.name ?? id
  const mine = (schedule?.shifts ?? []).filter((s) => s.employee_id === employeeId).sort((a, b) => a.day - b.day || a.start - b.start)
  const hours = mine.reduce((h, s) => h + paidMinutes(s) / 60, 0)
  const msgs = (outreach?.messages ?? []).filter((m) => (isOut(m) ? m.to_employee_id === employeeId : me && digits(m.from_phone) === digits(me.phone)))
  const lastOut = [...msgs].reverse().find(isOut)
  const answered = lastOut && msgs.slice(msgs.indexOf(lastOut) + 1).some((m) => !isOut(m) && (m.interpreted_as === 'accept' || m.interpreted_as === 'decline'))
  const offerOpen = !!lastOut && !answered && outreach?.status === 'texting' && outreach.current_rank === lastOut.outreach_rank
  const accepted = outreach?.accepted_employee_ids.includes(employeeId)

  const reply = async (body: string) => {
    if (!me) return
    setSending(body)
    try {
      await api.mockReply(me.phone, body)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSending(null)
    }
  }

  const [draft, setDraft] = useState('')
  const [told, setTold] = useState<Callout | null>(null)
  const tellManager = async (e: React.FormEvent) => {
    e.preventDefault()
    const body = draft.trim()
    if (!me || !body || !storeId) return
    setSending(body)
    setError(null)
    try {
      const r = await api.mockReply(me.phone, body, storeId)
      setTold(r.callout ?? null)
      setDraft('')
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSending(null)
    }
  }

  if (!storeId) return <Shell title="Shiftwright">Open this page from the store's Fix call-outs tab.</Shell>
  if (error && !cfg) return <Shell title="Shiftwright">Can't load your schedule: {error}</Shell>
  if (!cfg) return <Shell title="Shiftwright">Loading…</Shell>
  if (!me) return <Shell title="Shiftwright">No employee {employeeId} at this store.</Shell>

  return (
    <Shell title={me.name.split(' ')[0]} subtitle={cfg.store.name}>
      {offerOpen && lastOut && (
        <section className="mb-4 rounded-2xl border-2 border-pine bg-panel p-4">
          <div className="text-xs font-semibold tracking-wide text-pine-dark uppercase">Shift offer</div>
          <p className="mt-1 text-[15px] leading-snug">{lastOut.body}</p>
          <p className="mt-2 text-xs text-muted">Saying no is fine. Nothing changes for your other shifts.</p>
          {mockMessenger ? (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button
                type="button"
                disabled={!!sending}
                onClick={() => void reply('Yes, I can work it')}
                className="rounded-xl bg-pine py-3 text-base font-semibold text-white disabled:opacity-60"
              >
                {sending?.startsWith('Yes') ? 'Sending…' : 'Accept'}
              </button>
              <button
                type="button"
                disabled={!!sending}
                onClick={() => void reply("No, I can't")}
                className="rounded-xl border border-rule bg-panel py-3 text-base font-semibold text-ink disabled:opacity-60"
              >
                {sending?.startsWith('No') ? 'Sending…' : 'Decline'}
              </button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ink-2">Reply YES or NO to the text message.</p>
          )}
        </section>
      )}
      {mockMessenger && !offerOpen && (
        <form onSubmit={tellManager} className="mb-4 rounded-2xl border border-rule bg-panel p-4">
          <label htmlFor="tell" className="text-sm font-semibold">
            Can't make a shift? Message the store
          </label>
          <textarea
            id="tell"
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. I'm sick, can't come in tomorrow"
            className="mt-2 w-full resize-none rounded-xl border border-rule bg-paper px-3 py-2 text-[15px]"
          />
          <button
            type="submit"
            disabled={!draft.trim() || !!sending}
            className="mt-2 w-full rounded-xl bg-ink py-2.5 text-base font-semibold text-white disabled:opacity-50"
          >
            {sending && !sending.startsWith('Yes') && !sending.startsWith('No') ? 'Sending…' : 'Send'}
          </button>
          {told?.reply && <p className="mt-3 rounded-xl bg-pine-wash px-3 py-2 text-sm text-pine-dark">{told.reply}</p>}
          {told && !told.reply && <p className="mt-3 text-sm text-ink-2">Sent to your manager.</p>}
          {error && cfg && <p className="mt-2 text-sm text-gap">{error}</p>}
        </form>
      )}
      {accepted && !offerOpen && (
        <p className="mb-4 rounded-xl bg-pine-wash px-4 py-3 text-sm text-pine-dark">You picked up a shift. It's in your week below.</p>
      )}

      <section>
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Your week</h2>
          <span className="text-sm text-muted">
            {fmtDayDate(cfg.store.week_start, 0).date}–{fmtDayDate(cfg.store.week_start, 6).date} · {fmtHours(hours)}
          </span>
        </div>
        <ul className="mt-2 divide-y divide-rule-soft rounded-2xl border border-rule bg-panel">
          {WEEKDAY_NAMES.map((w, d) => {
            const day = mine.filter((s) => s.day === d)
            return (
              <li key={w} className="flex gap-3 px-4 py-3">
                <div className="w-12 shrink-0">
                  <div className="font-semibold">{w}</div>
                  <div className="text-xs text-muted">{fmtDayDate(cfg.store.week_start, d).date.split(' ')[1]}</div>
                </div>
                <div className="min-w-0 flex-1">
                  {day.length === 0 ? (
                    <span className="text-muted">Off</span>
                  ) : (
                    day.map((s) => (
                      <div key={s.id} className="mb-1 last:mb-0">
                        <div className="text-[15px] font-semibold">{fmtRange(s.start, s.end)}</div>
                        <div className="text-sm text-ink-2">
                          {s.segments.map((g) => `${roleName(g.role_id)}${s.segments.length > 1 ? ` ${fmtRange(g.start, g.end)}` : ''}`).join(' · ')}
                        </div>
                        {(s.breaks ?? []).map((b, i) => (
                          <div key={i} className="text-xs text-muted">
                            {b.kind === 'meal' ? 'Meal' : 'Break'} {fmtRange(b.start, b.end)} ({b.paid ? 'paid' : 'unpaid'})
                          </div>
                        ))}
                      </div>
                    ))
                  )}
                </div>
              </li>
            )
          })}
        </ul>
        {!schedule && <p className="mt-2 text-sm text-muted">Your schedule hasn't been posted yet.</p>}
      </section>

      {msgs.length > 0 && (
        <section className="mt-5">
          <h2 className="text-base font-semibold">Messages from the store</h2>
          <div className="mt-2 space-y-2">
            {msgs.map((m) =>
              isOut(m) ? (
                <div key={m.id} className="mr-8">
                  <div className="rounded-2xl rounded-bl-sm bg-panel px-3.5 py-2.5 text-[15px] ring-1 ring-rule">{m.body}</div>
                  <div className="mt-0.5 text-[11px] text-muted">{clock(m.sent_at)}</div>
                </div>
              ) : (
                <div key={m.id} className="ml-8 text-right">
                  <div className="inline-block rounded-2xl rounded-br-sm bg-pine px-3.5 py-2.5 text-left text-[15px] text-white">{m.body}</div>
                  <div className="mt-0.5 text-[11px] text-muted">{clock(m.received_at)}</div>
                </div>
              ),
            )}
          </div>
        </section>
      )}
      <p className="mt-6 pb-6 text-center text-[11px] text-muted">Questions about a shift? Talk to your leader on duty.</p>
    </Shell>
  )
}

function clock(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : fmtTime(d.getHours() * 60 + d.getMinutes())
}

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex h-full max-w-[430px] flex-col overflow-hidden bg-paper">
      <header className="bg-ink px-5 pt-6 pb-4 text-white">
        <div className="text-xl font-semibold">{title}</div>
        {subtitle && <div className="text-sm text-white/70">{subtitle}</div>}
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4 text-ink">{children}</main>
    </div>
  )
}
