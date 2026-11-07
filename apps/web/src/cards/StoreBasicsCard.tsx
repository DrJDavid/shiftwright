import { useId, useState } from 'react'
import type { DayHours } from '../contracts'
import type { StoreBasicsProps, StoreBasicsResult } from '../api/protocol'
import { fmtDayDate, WEEKDAY_NAMES } from '../lib/format'
import { CardFrame, Field, inputCls, type CardProps } from './CardFrame'
import { fromHHMM, toHHMM } from './time'
import { SECTOR_LABEL } from '../lib/vocab'
import type { Sector } from '../contracts'


type Row = { open: number; close: number; closed: boolean }

export function StoreBasicsCard({ props, status, result, onSubmit, onCancel }: CardProps<StoreBasicsProps, StoreBasicsResult>) {
  const formId = useId()
  const p = props ?? {}
  const [sector, setSector] = useState<Sector | ''>(p.sector ?? '')
  const [description, setDescription] = useState(p.business_description ?? '')
  const [splits, setSplits] = useState((p.max_shifts_per_day ?? 1) > 1)
  const [name, setName] = useState(p.name ?? '')
  const [state, setState] = useState(p.jurisdiction?.state ?? '')
  const [city, setCity] = useState(p.jurisdiction?.city ?? '')
  const [timezone, setTimezone] = useState(p.timezone ?? 'America/Chicago')
  const [slot, setSlot] = useState<15 | 30 | 60>(p.slot_minutes ?? 30)
  const [weekStart, setWeekStart] = useState(p.week_start ?? '')
  const [school, setSchool] = useState<'unknown' | 'yes' | 'no'>(
    p.school_week === true ? 'yes' : p.school_week === false ? 'no' : 'unknown',
  )
  // A blank store has no hours yet: start every day open 9a–9p for the leader to adjust and confirm,
  // rather than every day closed.
  const noHours = !p.hours || p.hours.length === 0
  const [rows, setRows] = useState<Row[]>(() =>
    WEEKDAY_NAMES.map((_, day) => {
      const h = p.hours?.find((x) => x.day === day)
      return h ? { open: h.open, close: h.close, closed: false } : noHours ? { open: 540, close: 1260, closed: false } : { open: 480, close: 1320, closed: true }
    }),
  )
  const [allOpen, setAllOpen] = useState(rows.find((r) => !r.closed)?.open ?? 540)
  const [allClose, setAllClose] = useState(rows.find((r) => !r.closed)?.close ?? 1260)

  const isMonday = weekStart ? new Date(`${weekStart}T12:00:00Z`).getUTCDay() === 1 : false
  const hoursOk = rows.every((r) => r.closed || r.close > r.open)
  const valid = name.trim() !== '' && /^[A-Za-z]{2}$/.test(state) && isMonday && hoursOk

  const shown = status === 'submitted' ? (result ?? {}) : {}
  const summary = (
    <>
      {shown.sector ? `${SECTOR_LABEL[shown.sector]} · ` : ''}
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
      school_week: school === 'unknown' ? null : school === 'yes',
      sector: sector || null,
      business_description: description.trim(),
      max_shifts_per_day: splits ? 2 : 1,
    })
  }

  const setRow = (day: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, i) => (i === day ? { ...r, ...patch } : r)))

  return (
    <CardFrame title="Store basics" status={status} summary={summary} onCancel={onCancel} submitLabel="Confirm store" canSubmit={valid} formId={formId}>
      <form id={formId} onSubmit={submit} className="space-y-3">
        <Field label="What kind of business is this?" hint="Only used to decide which labor laws apply.">
          <select className={inputCls} value={sector} onChange={(e) => setSector(e.target.value as Sector | '')}>
            <option value="">Not sure yet</option>
            {(Object.keys(SECTOR_LABEL) as Sector[]).map((k) => (
              <option key={k} value={k}>
                {SECTOR_LABEL[k]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="In a few words">
          <input
            className={inputCls}
            placeholder="e.g. family taqueria, 30 seats"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
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
        <div className="grid grid-cols-2 gap-2">
          <Field label="Time zone">
            <input className={inputCls} value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          </Field>
          <Field label="School in session this week?" hint="Sets which minor-hour limits apply.">
            <select className={inputCls} value={school} onChange={(e) => setSchool(e.target.value as 'unknown' | 'yes' | 'no')}>
              <option value="unknown">Not sure (strictest)</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={splits} onChange={(e) => setSplits(e.target.checked)} />
          Split shifts allowed (someone can work lunch and dinner on the same day)
        </label>
        {weekStart && !isMonday && <p className="text-sm text-gap">Pick a Monday. Weeks run Monday to Sunday.</p>}
        <div>
          <span className="mb-1 block text-sm text-ink-2">Open hours{noHours ? ' (a starting guess: adjust, then confirm)' : ''}</span>
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5 rounded-md bg-paper px-2 py-1.5 text-sm">
            <span className="text-ink-2">Same hours every day:</span>
            <input
              type="time"
              step={slot * 60}
              aria-label="Every day open"
              className="w-[6.25rem] rounded border border-rule bg-panel px-1 py-0.5 text-xs"
              value={toHHMM(allOpen)}
              onChange={(e) => setAllOpen(fromHHMM(e.target.value))}
            />
            <span className="text-muted">to</span>
            <input
              type="time"
              step={slot * 60}
              aria-label="Every day close"
              className="w-[6.25rem] rounded border border-rule bg-panel px-1 py-0.5 text-xs"
              value={toHHMM(allClose)}
              onChange={(e) => setAllClose(fromHHMM(e.target.value))}
            />
            <button
              type="button"
              className="rounded border border-ink/40 px-2 py-0.5 text-xs font-semibold hover:border-ink"
              onClick={() => setRows((rs) => rs.map((r) => (r.closed ? r : { ...r, open: allOpen, close: allClose })))}
            >
              Apply to open days
            </button>
            <span className="w-full text-xs text-muted">Closed on:</span>
            <span className="flex gap-1">
              {WEEKDAY_NAMES.map((w, d) => (
                <button
                  key={w}
                  type="button"
                  aria-pressed={rows[d].closed}
                  onClick={() => setRow(d, { closed: !rows[d].closed, ...(rows[d].closed ? { open: allOpen, close: allClose } : {}) })}
                  className={`rounded px-1.5 py-0.5 text-xs font-semibold ${rows[d].closed ? 'bg-ink text-white' : 'border border-rule text-ink-2 hover:border-ink'}`}
                >
                  {w}
                </button>
              ))}
            </span>
          </div>
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
                      className="w-[6.25rem] rounded border border-rule px-1 py-0.5 text-xs"
                      value={toHHMM(r.open)}
                      onChange={(e) => setRow(day, { open: fromHHMM(e.target.value) })}
                    />
                    <span className="text-muted">to</span>
                    <input
                      type="time"
                      step={slot * 60}
                      aria-label={`${WEEKDAY_NAMES[day]} close`}
                      className="w-[6.25rem] rounded border border-rule px-1 py-0.5 text-xs"
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
