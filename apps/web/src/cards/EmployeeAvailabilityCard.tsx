import { useId, useState } from 'react'
import type { AvailabilityEntry, AvailabilityKind } from '../contracts'
import type { EmployeeAvailabilityProps, EmployeeAvailabilityResult } from '../api/protocol'
import { fmtRange, WEEKDAY_NAMES } from '../lib/format'
import { CardFrame, type CardProps } from './CardFrame'
import { fromHHMM, toHHMM } from './time'

const KIND: Record<AvailabilityKind, string> = { unavailable: "Can't work", preferred_off: 'Prefers off', preferred_on: 'Prefers to work' }

function when(e: AvailabilityEntry) {
  const day = e.on_date ? e.on_date : e.weekday != null ? `Every ${WEEKDAY_NAMES[e.weekday]}` : 'Every day'
  const all = e.start <= 0 && e.end >= 1440
  return `${day}${all ? ', all day' : `, ${fmtRange(e.start, e.end)}`}`
}

export function EmployeeAvailabilityCard({ props, status, result, onSubmit, onCancel }: CardProps<EmployeeAvailabilityProps, EmployeeAvailabilityResult>) {
  const formId = useId()
  const [entries, setEntries] = useState<AvailabilityEntry[]>(props?.parsed ?? [])
  const set = (i: number, patch: Partial<AvailabilityEntry>) => setEntries((es) => es.map((e, j) => (j === i ? { ...e, ...patch } : e)))
  const valid = entries.every((e) => e.end > e.start)
  const name = props?.employee?.name ?? 'this person'
  const summary = status === 'submitted' && result ? `${name}: ${result.confirmed.length === 0 ? 'no limits' : result.confirmed.map(when).join('; ')}.` : null

  return (
    <CardFrame title={`Availability for ${name}`} status={status} summary={summary} onCancel={onCancel} submitLabel="Confirm" canSubmit={valid} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onSubmit({ confirmed: entries })
        }}
        className="space-y-2"
      >
        {props?.original_text && (
          <blockquote className="rounded-md bg-paper px-3 py-2 text-sm text-ink-2 italic">"{props.original_text}"</blockquote>
        )}
        <p className="text-sm text-ink-2">Here's how I read it. Fix anything that's wrong.</p>
        {entries.length === 0 && <p className="text-sm text-muted">No limits.</p>}
        {entries.map((e, i) => (
          <div key={i} className="flex flex-wrap items-center gap-1.5 rounded-md border border-rule p-2 text-sm">
            <select className="rounded border border-rule px-1 py-0.5" aria-label="Type" value={e.kind} onChange={(ev) => set(i, { kind: ev.target.value as AvailabilityKind })}>
              {(Object.keys(KIND) as AvailabilityKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND[k]}
                </option>
              ))}
            </select>
            {e.on_date ? (
              <input type="date" aria-label="Date" className="rounded border border-rule px-1 py-0.5" value={e.on_date} onChange={(ev) => set(i, { on_date: ev.target.value })} />
            ) : (
              <select
                className="rounded border border-rule px-1 py-0.5"
                aria-label="Day"
                value={e.weekday ?? ''}
                onChange={(ev) => set(i, { weekday: ev.target.value === '' ? null : Number(ev.target.value) })}
              >
                <option value="">Every day</option>
                {WEEKDAY_NAMES.map((d, j) => (
                  <option key={d} value={j}>
                    {d}
                  </option>
                ))}
              </select>
            )}
            <input type="time" aria-label="From" className="rounded border border-rule px-1 py-0.5" value={toHHMM(e.start)} onChange={(ev) => set(i, { start: fromHHMM(ev.target.value) })} />
            <span className="text-muted">to</span>
            <input
              type="time"
              aria-label="To"
              className="rounded border border-rule px-1 py-0.5"
              value={toHHMM(Math.min(e.end, 1439))}
              onChange={(ev) => set(i, { end: fromHHMM(ev.target.value) || 1440 })}
            />
            <button type="button" aria-label="Remove" className="ml-auto text-muted hover:text-gap" onClick={() => setEntries((es) => es.filter((_, j) => j !== i))}>
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="text-sm font-semibold text-pine hover:underline"
          onClick={() => setEntries((es) => [...es, { weekday: 0, start: 0, end: 1440, kind: 'unavailable', source: 'employee' }])}
        >
          + Add
        </button>
      </form>
    </CardFrame>
  )
}
