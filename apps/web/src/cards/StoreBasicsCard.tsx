import { useId, useState } from 'react'
import type { DayHours } from '../contracts'
import type { StoreBasicsProps, StoreBasicsResult } from '../api/protocol'
import { fmtDayDate, WEEKDAY_NAMES } from '../lib/format'
import { CardFrame, Field, inputCls, type CardProps } from './CardFrame'

const toHHMM = (m: number) => `${String(Math.floor((m % 1440) / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
const fromHHMM = (s: string) => {
  const [h, m] = s.split(':').map(Number)
  return (h || 0) * 60 + (m || 0)
}

type Row = { open: number; close: number; closed: boolean }

export function StoreBasicsCard({ props, status, result, onSubmit, onCancel }: CardProps<StoreBasicsProps, StoreBasicsResult>) {
  const formId = useId()
  const p = props ?? {}
  const [name, setName] = useState(p.name ?? '')
  const [state, setState] = useState(p.jurisdiction?.state ?? '')
  const [city, setCity] = useState(p.jurisdiction?.city ?? '')
  const [timezone, setTimezone] = useState(p.timezone ?? 'America/Chicago')
  const [slot, setSlot] = useState<15 | 30 | 60>(p.slot_minutes ?? 30)
  const [weekStart, setWeekStart] = useState(p.week_start ?? '')
  const [rows, setRows] = useState<Row[]>(() =>
    WEEKDAY_NAMES.map((_, day) => {
      const h = p.hours?.find((x) => x.day === day)
      return h ? { open: h.open, close: h.close, closed: false } : { open: 480, close: 1320, closed: true }
    }),
  )

  const isMonday = weekStart ? new Date(`${weekStart}T12:00:00Z`).getUTCDay() === 1 : false
  const hoursOk = rows.every((r) => r.closed || r.close > r.open)
  const valid = name.trim() !== '' && /^[A-Za-z]{2}$/.test(state) && isMonday && hoursOk

  const shown = status === 'submitted' ? (result ?? {}) : {}
  const summary = (
    <>
      {shown.name ?? name}, {shown.jurisdiction?.city ? `${titleCase(shown.jurisdiction.city)}, ` : ''}
      {shown.jurisdiction?.state ?? state}. Week of {weekLabel(shown.week_start ?? weekStart)}.
    </>
  )

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!valid) return
    const hours: DayHours[] = rows.flatMap((r, day) => (r.closed ? [] : [{ day, open: r.open, close: r.close }]))
    onSubmit({
      name: name.trim(),
      jurisdiction: { state: state.toUpperCase(), city: city.trim() ? city.trim().toLowerCase() : null },
      timezone,
      slot_minutes: slot,
      week_start: weekStart,
      hours,
    })
  }

  const setRow = (day: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, i) => (i === day ? { ...r, ...patch } : r)))

  return (
    <CardFrame title="Store basics" status={status} summary={summary} onCancel={onCancel} submitLabel="Confirm store" canSubmit={valid} formId={formId}>
      <form id={formId} onSubmit={submit} className="space-y-3">
        <Field label="Store name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <div className="grid grid-cols-[5rem_1fr] gap-2">
          <Field label="State">
            <input className={`${inputCls} uppercase`} value={state} maxLength={2} onChange={(e) => setState(e.target.value)} required />
          </Field>
          <Field label="City" hint="Some cities have their own scheduling laws.">
            <input className={inputCls} value={city} onChange={(e) => setCity(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Week starts on Monday">
            <input type="date" className={inputCls} value={weekStart} onChange={(e) => setWeekStart(e.target.value)} required />
          </Field>
          <Field label="Time slots">
            <select className={inputCls} value={slot} onChange={(e) => setSlot(Number(e.target.value) as 15 | 30 | 60)}>
              <option value={15}>15 min</option>
              <option value={30}>30 min</option>
              <option value={60}>60 min</option>
            </select>
          </Field>
        </div>
        <Field label="Time zone">
          <input className={inputCls} value={timezone} onChange={(e) => setTimezone(e.target.value)} />
        </Field>
        {weekStart && !isMonday && <p className="text-sm text-gap">Pick a Monday. Weeks run Monday to Sunday.</p>}
        <div>
          <span className="mb-1 block text-sm text-ink-2">Open hours</span>
          <div className="divide-y divide-rule-soft rounded-md border border-rule">
            {rows.map((r, day) => (
              <div key={day} className="flex items-center gap-2 px-2.5 py-1 text-sm">
                <span className="w-9 font-medium">{WEEKDAY_NAMES[day]}</span>
                {r.closed ? (
                  <span className="flex-1 text-muted">Closed</span>
                ) : (
                  <>
                    <input
                      type="time"
                      step={slot * 60}
                      aria-label={`${WEEKDAY_NAMES[day]} open`}
                      className="w-[7.5rem] rounded border border-rule px-1 py-0.5"
                      value={toHHMM(r.open)}
                      onChange={(e) => setRow(day, { open: fromHHMM(e.target.value) })}
                    />
                    <span className="text-muted">to</span>
                    <input
                      type="time"
                      step={slot * 60}
                      aria-label={`${WEEKDAY_NAMES[day]} close`}
                      className="w-[7.5rem] rounded border border-rule px-1 py-0.5"
                      value={toHHMM(r.close)}
                      onChange={(e) => setRow(day, { close: fromHHMM(e.target.value) })}
                    />
                    <span className="flex-1 text-xs text-gap">{r.close > r.open ? '' : 'Ends before it opens'}</span>
                  </>
                )}
                <label className="flex items-center gap-1 text-xs text-ink-2">
                  <input type="checkbox" checked={r.closed} onChange={(e) => setRow(day, { closed: e.target.checked })} />
                  Closed
                </label>
              </div>
            ))}
          </div>
        </div>
      </form>
    </CardFrame>
  )
}

function weekLabel(iso: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? fmtDayDate(iso, 0).date : iso
}

function titleCase(s: string) {
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}
