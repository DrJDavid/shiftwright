import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Employee, Gap, LawRule, Schedule, Shift, StoreConfig } from '../contracts'
import { fmtDayDate, fmtHours, fmtMoney, fmtMoneyShort, fmtRange } from '../lib/format'
import { roleColors } from '../lib/roles'
import { shiftWage } from '../lib/vocab'
import { humanizer } from '../lib/humanize'
import { minorProtections } from '../lib/minors'
import { MinorLine } from './MinorLine'

type Props = {
  schedule: Schedule
  config: StoreConfig
  onGapClick?: (g: Gap) => void
  onDayClick?: (day: number) => void
  /** Reported call-outs (Fix tab): their shifts are shown struck through. */
  callouts?: { employee_id: string; day: number }[]
  /** Law pack rules, for the minor-protection shield on rows. */
  lawRules?: LawRule[]
}
type Hover = { x: number; y: number; content: ReactNode } | null

/** The engine's fix_day names shifts it adds for a call-out `…-callin` (packages/engine fix.py). */
const isCallIn = (s: Shift) => s.id.endsWith('-callin')

function paidHours(s: Shift) {
  const unpaid = (s.breaks ?? []).filter((b) => !b.paid).reduce((m, b) => m + b.end - b.start, 0)
  return (s.end - s.start - unpaid) / 60
}

export function ScheduleGrid({ schedule, config, onGapClick, onDayClick, callouts = [], lawRules = [] }: Props) {
  const [groupBy, setGroupBy] = useState<'department' | 'hours'>('department')
  const [hover, setHover] = useState<Hover>(null)
  const colors = useMemo(() => roleColors(config.roles), [config.roles])
  const roleName = useMemo(() => new Map(config.roles.map((r) => [r.id, r.name])), [config.roles])
  const roleById = useMemo(() => new Map(config.roles.map((r) => [r.id, r])), [config.roles])
  const h = useMemo(() => humanizer(config), [config])
  const protectedMinors = useMemo(
    () => new Map(minorProtections(config, schedule, lawRules).map((m) => [m.employee.id, m])),
    [config, schedule, lawRules],
  )
  const shifts = useMemo(() => schedule.shifts ?? [], [schedule.shifts])
  const gaps = schedule.gaps ?? []
  const days = [0, 1, 2, 3, 4, 5, 6]

  // One shared time axis for every cell so bars line up down each column.
  const [axisStart, axisEnd] = useMemo(() => {
    const pre = config.store.pre_open_minutes ?? 60
    const post = config.store.post_close_minutes ?? 60
    let lo = Math.min(...config.store.hours.map((h) => h.open - pre), ...shifts.map((s) => s.start))
    let hi = Math.max(...config.store.hours.map((h) => h.close + post), ...shifts.map((s) => s.end))
    if (!Number.isFinite(lo)) lo = 360
    if (!Number.isFinite(hi)) hi = 1380
    return [Math.floor(lo / 60) * 60, Math.ceil(hi / 60) * 60]
  }, [config.store, shifts])
  const pct = (t: number) => `${((t - axisStart) / (axisEnd - axisStart)) * 100}%`
  const width = (a: number, b: number) => `${((b - a) / (axisEnd - axisStart)) * 100}%`
  // Positions inside one shift's bar (segments and breaks), as a share of the shift's own span.
  const rel = (s: Shift, t: number) => `${((t - s.start) / Math.max(1, s.end - s.start)) * 100}%`
  const relW = (s: Shift, a: number, b: number) => `${((b - a) / Math.max(1, s.end - s.start)) * 100}%`
  const isOut = (s: Shift) => callouts.some((c) => c.employee_id === s.employee_id && c.day === s.day)

  // Grouped by home department (store order), most hours first inside each group; or one list by hours.
  const groups = useMemo(() => {
    const hours = new Map<string, number>()
    for (const s of shifts) hours.set(s.employee_id, (hours.get(s.employee_id) ?? 0) + paidHours(s))
    const rows = [...config.employees]
      .map((e) => ({ e, hours: hours.get(e.id) ?? 0 }))
      .sort((a, b) => b.hours - a.hours || a.e.name.localeCompare(b.e.name))
    if (groupBy === 'hours') return [{ id: 'all', name: '', rows }]
    const out = config.departments.map((d) => ({ id: d.id, name: d.name, rows: rows.filter((r) => r.e.home_department_id === d.id) }))
    const known = new Set(config.departments.map((d) => d.id))
    const other = rows.filter((r) => !known.has(r.e.home_department_id))
    if (other.length) out.push({ id: '_other', name: 'Other', rows: other })
    return out.filter((g) => g.rows.length > 0)
  }, [config.employees, config.departments, shifts, groupBy])
  const rows = groups.flatMap((g) => g.rows)

  const byCell = useMemo(() => {
    const m = new Map<string, Shift[]>()
    for (const s of shifts) {
      const k = `${s.employee_id}|${s.day}`
      m.set(k, [...(m.get(k) ?? []), s])
    }
    for (const v of m.values()) v.sort((a, b) => a.start - b.start)
    return m
  }, [shifts])

  const gapsByDay = days.map((d) => gaps.filter((g) => g.day === d))
  const show = (ev: React.MouseEvent, content: ReactNode) => setHover({ x: ev.clientX, y: ev.clientY, content })

  const [pinned, setPinned] = useState<{ x: number; y: number; e: Employee; s: Shift } | null>(null)
  useEffect(() => {
    if (!pinned) return
    const close = (ev: KeyboardEvent) => ev.key === 'Escape' && setPinned(null)
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [pinned])

  const shiftDetail = (e: Employee, s: Shift, full = false) => (
    <div className="space-y-1">
      <div className="font-semibold">
        {e.name}
        {isCallIn(s) && <span className="ml-1.5 text-xs font-semibold text-pine-dark">Call-in: covering a call-out</span>}
      </div>
      {/* v1.2 Shift.why: engine one-liners, headline first. Hover shows the headline; click shows all. */}
      {(s.why ?? []).length > 0 &&
        (full ? (
          <ul className="space-y-0.5 rounded bg-pine-wash px-2 py-1.5 text-pine-dark">
            {(s.why ?? []).map((w, i) => (
              <li key={i} className={i === 0 ? 'font-semibold' : ''}>
                {w}
              </li>
            ))}
          </ul>
        ) : (
          <div className="font-medium text-pine-dark">
            {h(s.why![0])}
            {s.why!.length > 1 && <span className="font-normal text-muted"> · click for {s.why!.length - 1} more</span>}
          </div>
        ))}
      <div className="text-ink-2">
        {fmtDayDate(schedule.week_start, s.day).weekday} {fmtRange(s.start, s.end)}, {fmtHours(paidHours(s))} paid,{' '}
        {(() => {
          // SEMANTICS #20: shifts entirely in tipped roles pay the tipped cash wage (before any overtime premium).
          const w = shiftWage(s, e, roleById)
          return (
            <>
              {fmtMoney(paidHours(s) * w.wage)}
              {w.tipped && <span className="text-warn"> at the tipped wage {fmtMoney(w.wage, { cents: true })}/h</span>}
            </>
          )
        })()}
      </div>
      <ul>
        {s.segments.map((g, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="inline-block size-2.5 rounded-sm" style={{ background: colors.get(g.role_id) }} />
            {roleName.get(g.role_id) ?? g.role_id}, {fmtRange(g.start, g.end)}
          </li>
        ))}
        {(s.breaks ?? []).map((b, i) => (
          <li key={`b${i}`} className="text-muted">
            {b.kind === 'meal' ? 'Meal' : 'Rest'} break {fmtRange(b.start, b.end)} ({b.paid ? 'paid' : 'unpaid'})
          </li>
        ))}
      </ul>
    </div>
  )

  const gapDetail = (g: Gap) => (
    <div className="space-y-1">
      <div className="font-semibold text-gap">
        {roleName.get(g.role_id) ?? g.role_id} uncovered, {fmtRange(g.start, g.end)}
      </div>
      <div className="text-ink-2">
        {g.missing_headcount} {g.missing_headcount === 1 ? 'person' : 'people'} short, {fmtMoney(g.penalty_dollars)} penalty
      </div>
      {g.reasons && g.reasons.length > 0 && (
        <div className="text-muted">
          {g.reasons.length} trained {g.reasons.length === 1 ? 'person' : 'people'} could not cover it.
        </div>
      )}
      {onGapClick && <div className="text-xs text-muted">Click to see why.</div>}
    </div>
  )

  return (
    <div className="relative min-h-0 flex-1 overflow-auto" onMouseLeave={() => setHover(null)}>
      <table className="w-full table-fixed border-separate border-spacing-0 text-sm">
        <colgroup>
          <col className="w-36" />
          {days.map((d) => (
            <col key={d} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-10 bg-panel">
          <tr>
            <th className="border-b border-rule px-3 py-2 text-left align-bottom font-normal text-muted">
              <div>
                {rows.filter((r) => r.hours > 0).length} of {rows.length} scheduled
              </div>
              <label className="mt-0.5 flex items-center gap-1 text-xs">
                Group by
                <select
                  className="rounded border border-rule bg-panel px-0.5 text-xs text-ink"
                  value={groupBy}
                  onChange={(e) => setGroupBy(e.target.value as 'department' | 'hours')}
                >
                  <option value="department">Dept</option>
                  <option value="hours">Hours</option>
                </select>
              </label>
            </th>
            {days.map((d) => {
              const { weekday, date } = fmtDayDate(schedule.week_start, d)
              const dayGaps = gapsByDay[d]
              const closed = !config.store.hours.some((h) => h.day === d)
              const cost = dayGaps.reduce((c, g) => c + g.penalty_dollars, 0)
              return (
                <th key={d} className="border-b border-l border-rule px-2 py-2 text-left align-bottom font-normal">
                  <div className="truncate">
                    <span className="font-semibold text-ink">{weekday}</span> <span className="text-muted">{date.split(' ')[1]}</span>
                  </div>
                  {dayGaps.length && onDayClick ? (
                    <button
                      type="button"
                      onClick={() => onDayClick(d)}
                      className="block max-w-full truncate text-xs font-medium text-gap hover:underline"
                      title={`${dayGaps.length} uncovered stretches, ${fmtMoney(cost)} gap cost. See by role.`}
                    >
                      {fmtMoneyShort(cost)} gaps
                    </button>
                  ) : (
                    <div className={`truncate text-xs ${dayGaps.length ? 'font-medium text-gap' : 'text-muted'}`}>
                      {dayGaps.length ? `${fmtMoneyShort(cost)} gaps` : closed ? 'Closed' : 'Covered'}
                    </div>
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <Fragment key={g.id}>
              {g.name && (
                <tr>
                  <th
                    colSpan={8}
                    className="border-b border-rule bg-paper px-3 py-1 text-left text-xs font-semibold tracking-wide text-ink-2 uppercase"
                  >
                    {g.name}
                    <span className="ml-2 font-normal normal-case text-muted">
                      {g.rows.filter((r) => r.hours > 0).length} of {g.rows.length} scheduled ·{' '}
                      {fmtHours(g.rows.reduce((h, r) => h + r.hours, 0))}
                    </span>
                  </th>
                </tr>
              )}
              {g.rows.map(({ e, hours }) => (
                <tr key={e.id} className="group">
                  <th scope="row" className="border-b border-rule-soft bg-panel px-3 py-1.5 text-left font-normal group-hover:bg-paper">
                    <div className="flex items-center gap-1 truncate font-medium text-ink">
                      <span className="truncate">{e.name}</span>
                      {protectedMinors.has(e.id) && (
                        <span
                          className={`shrink-0 ${protectedMinors.get(e.id)!.workedBarred.length ? 'text-gap' : 'text-pine'}`}
                          aria-label="Minor kept off hazardous roles"
                          onMouseMove={(ev) => show(ev, <MinorLine m={protectedMinors.get(e.id)!} compact />)}
                          onMouseLeave={() => setHover(null)}
                        >
                          <svg viewBox="0 0 16 16" className="size-3.5" fill="currentColor" aria-hidden>
                            <path d="M8 1 2.5 3v4.2c0 3.4 2.3 6.4 5.5 7.8 3.2-1.4 5.5-4.4 5.5-7.8V3L8 1Zm-1 9.6L4.6 8.2l1-1L7 8.6l3.4-3.4 1 1L7 10.6Z" />
                          </svg>
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted">
                      {hours > 0 ? fmtHours(hours) : 'Off all week'}
                      {e.max_hours_week ? ` of ${fmtHours(e.max_hours_week)}` : ''}
                    </div>
                  </th>
                  {days.map((d) => {
                    const cell = byCell.get(`${e.id}|${d}`) ?? []
                    return (
                      <td key={d} className="border-b border-l border-rule-soft px-1.5 py-1.5 align-middle group-hover:bg-paper">
                        {cell.length > 0 && (
                          // v1.5 split shifts: every shift of the day on one track, so lunch + dinner read as two bars.
                          <div className={cell.every((s) => isOut(s)) ? 'opacity-40' : ''}>
                            <div className="relative h-3">
                              {cell.map((s) => (
                                <div
                                  key={s.id}
                                  className={`absolute top-0 h-full cursor-pointer ${isOut(s) ? 'opacity-40' : ''}`}
                                  style={{ left: pct(s.start), width: width(s.start, s.end) }}
                                  onMouseMove={(ev) => !pinned && show(ev, shiftDetail(e, s))}
                                  onMouseLeave={() => setHover(null)}
                                  onClick={(ev) => {
                                    setHover(null)
                                    setPinned({ x: ev.clientX, y: ev.clientY, e, s })
                                  }}
                                >
                                  {s.segments.map((g, i) => (
                                    <div
                                      key={i}
                                      className="absolute top-0 h-full first:rounded-l-sm last:rounded-r-sm"
                                      style={{ left: rel(s, g.start), width: relW(s, g.start, g.end), background: colors.get(g.role_id) }}
                                    />
                                  ))}
                                  {/* v1.1: breaks may sit off the slot grid (5-minute steps); cut them out at minute precision. */}
                                  {(s.breaks ?? []).map((b, i) => (
                                    <div
                                      key={`b${i}`}
                                      className="absolute -top-px h-[calc(100%+2px)] bg-panel group-hover:bg-paper"
                                      style={{ left: rel(s, b.start), width: `max(2px, ${relW(s, b.start, b.end)})` }}
                                    />
                                  ))}
                                </div>
                              ))}
                            </div>
                            <div className="mt-0.5 truncate text-xs text-ink-2">
                              {cell.map((s, i) => (
                                <span key={s.id} className={isOut(s) ? 'font-semibold text-gap' : ''}>
                                  {i > 0 ? ', ' : ''}
                                  {isOut(s) ? <span className="line-through">{fmtRange(s.start, s.end)}</span> : fmtRange(s.start, s.end)}
                                  {isOut(s) && ' called out'}
                                  {isCallIn(s) && (
                                    <span className="ml-1 rounded bg-pine-wash px-1 text-[10px] font-semibold tracking-wide text-pine-dark uppercase">
                                      Call-in
                                    </span>
                                  )}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
        <tfoot className="sticky bottom-0 z-10 bg-panel">
          <tr>
            <th className="border-t-2 border-gap/60 px-3 py-2 text-left font-semibold text-gap">Uncovered</th>
            {days.map((d) => (
              <td key={d} className="border-t-2 border-l border-t-gap/60 border-l-rule-soft px-1.5 py-2">
                <div className="relative h-3 rounded-sm bg-rule-soft">
                  {gapsByDay[d].map((g, i) => (
                    <button
                      type="button"
                      key={i}
                      aria-label={`${roleName.get(g.role_id) ?? g.role_id} uncovered ${fmtRange(g.start, g.end)}: why?`}
                      className="absolute top-0 h-full cursor-pointer bg-gap hover:outline-2 hover:outline-ink"
                      style={{ left: pct(g.start), width: width(g.start, g.end), opacity: Math.min(1, 0.45 + 0.25 * g.missing_headcount) }}
                      onMouseMove={(ev) => show(ev, gapDetail(g))}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => {
                        setHover(null)
                        onGapClick?.(g)
                      }}
                    />
                  ))}
                </div>
              </td>
            ))}
          </tr>
        </tfoot>
      </table>

      {pinned && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setPinned(null)} aria-hidden />
          <div
            role="dialog"
            aria-label={`${pinned.e.name}'s shift`}
            className="fixed z-50 w-80 rounded-md border border-rule bg-panel px-3 py-2.5 text-sm shadow-xl"
            style={{ left: Math.min(pinned.x + 10, window.innerWidth - 340), top: Math.min(pinned.y + 10, window.innerHeight - 260) }}
          >
            {shiftDetail(pinned.e, pinned.s, true)}
            {(pinned.s.why ?? []).length === 0 && (
              <p className="mt-1 text-xs text-muted">No reasons were recorded for this shift.</p>
            )}
            <button type="button" onClick={() => setPinned(null)} className="mt-2 text-xs text-muted hover:text-ink">
              Close
            </button>
          </div>
        </>
      )}

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-rule bg-panel px-3 py-2 text-sm shadow-lg"
          style={{
            left: Math.min(hover.x + 14, window.innerWidth - 330),
            top: Math.min(hover.y + 14, window.innerHeight - 160),
          }}
        >
          {hover.content}
        </div>
      )}
    </div>
  )
}
