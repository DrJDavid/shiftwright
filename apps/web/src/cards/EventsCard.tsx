import { useId, useState } from 'react'
import type { Event, EventKind } from '../contracts'
import type { EventsProps, EventsResult } from '../api/protocol'
import { WEEKDAY_NAMES } from '../lib/format'
import { CardFrame, inputCls, type CardProps } from './CardFrame'
import { fromHHMM, toHHMM } from './time'
import { uniqueId } from './ids'
import { EVENT_LABEL, eventKindsFor, eventName } from '../lib/vocab'
import { useOptionalCardEnv } from './context'


export function EventsCard({ props, status, result, onSubmit, onCancel }: CardProps<EventsProps, EventsResult>) {
  const formId = useId()
  const env = useOptionalCardEnv()
  const kinds = eventKindsFor(env?.sector)
  const [events, setEvents] = useState<Event[]>(props?.events ?? [])
  const set = (i: number, patch: Partial<Event>) => setEvents((es) => es.map((e, j) => (j === i ? { ...e, ...patch } : e)))
  const valid = events.every((e) => e.end > e.start)
  const shown = status === 'submitted' ? result : undefined
  const summary = shown
    ? shown.events.length === 0
      ? 'No events this week.'
      : shown.events.map((e) => `${eventName(e)} ${WEEKDAY_NAMES[e.day]}`).join(', ')
    : null

  return (
    <CardFrame title="This week's events" status={status} summary={summary} onCancel={onCancel} submitLabel="Save events" canSubmit={valid} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onSubmit({ events })
        }}
        className="space-y-2"
      >
        <p className="text-sm text-ink-2">Trucks, floor sets and promos change how many people you need.</p>
        {events.length === 0 && <p className="text-sm text-muted">No events yet.</p>}
        {events.map((ev, i) => (
          <div key={ev.id} className="space-y-1 rounded-md border border-rule p-2">
            <div className="grid grid-cols-[1fr_5rem_1.5rem] gap-1.5">
              <select className={inputCls} aria-label="Event type" value={ev.kind} onChange={(e) => set(i, { kind: e.target.value as EventKind })}>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {EVENT_LABEL[k]}
                  </option>
                ))}
              </select>
              <select className={inputCls} aria-label="Day" value={ev.day} onChange={(e) => set(i, { day: Number(e.target.value) })}>
                {WEEKDAY_NAMES.map((d, j) => (
                  <option key={d} value={j}>
                    {d}
                  </option>
                ))}
              </select>
              <button type="button" aria-label="Remove event" className="text-muted hover:text-gap" onClick={() => setEvents((es) => es.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
            <div className="flex items-center gap-1.5 text-sm">
              <input type="time" aria-label="Start" className="rounded border border-rule px-1 py-0.5" value={toHHMM(ev.start)} onChange={(e) => set(i, { start: fromHHMM(e.target.value) })} />
              <span className="text-muted">to</span>
              <input type="time" aria-label="End" className="rounded border border-rule px-1 py-0.5" value={toHHMM(ev.end)} onChange={(e) => set(i, { end: fromHHMM(e.target.value) })} />
              {ev.end <= ev.start && <span className="text-xs text-gap">Ends before it starts</span>}
            </div>
            <input
              className={inputCls}
              placeholder={`Name, e.g. ${ev.kind === 'delivery' ? 'Sysco delivery' : ev.kind === 'private_event' ? 'Rehearsal dinner' : 'Tuesday truck'}`}
              aria-label="Event name"
              value={ev.label ?? ''}
              onChange={(e) => set(i, { label: e.target.value })}
            />
            <input className={inputCls} placeholder="Note (optional)" value={ev.note ?? ''} onChange={(e) => set(i, { note: e.target.value })} />
          </div>
        ))}
        <button
          type="button"
          className="text-sm font-semibold text-pine hover:underline"
          onClick={() =>
            setEvents((es) => [...es, { id: uniqueId(es.map((e) => e.id), `ev_${es.length + 1}`), kind: kinds[0], day: 1, start: 240, end: 600, note: '' }])
          }
        >
          + Add event
        </button>
      </form>
    </CardFrame>
  )
}
