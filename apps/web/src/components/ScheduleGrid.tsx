import { useMemo, useState, type ReactNode } from 'react'
import type { Employee, Gap, Schedule, Shift, StoreConfig } from '../contracts'
import { fmtDayDate, fmtHours, fmtMoney, fmtRange } from '../lib/format'
import { roleColors } from '../lib/roles'

type Props = { schedule: Schedule; config: StoreConfig }
type Hover = { x: number; y: number; content: ReactNode } | null

function paidHours(s: Shift) {
  const unpaid = (s.breaks ?? []).filter((b) => !b.paid).reduce((m, b) => m + b.end - b.start, 0)
  return (s.end - s.start - unpaid) / 60
}

export function ScheduleGrid({ schedule, config }: Props) {
  const [hover, setHover] = useState<Hover>(null)
  const colors = useMemo(() => roleColors(config.roles), [config.roles])
  const roleName = useMemo(() => new Map(config.roles.map((r) => [r.id, r.name])), [config.roles])
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

  // Show everyone scheduled, then everyone else, by most hours first.
  const rows = useMemo(() => {
    const hours = new Map<string, number>()
    for (const s of shifts) hours.set(s.employee_id, (hours.get(s.employee_id) ?? 0) + paidHours(s))
    return [...config.employees]
      .map((e) => ({ e, hours: hours.get(e.id) ?? 0 }))
      .sort((a, b) => b.hours - a.hours || a.e.name.localeCompare(b.e.name))
  }, [config.employees, shifts])

  const byCell = useMemo(() => {
    const m = new Map<string, Shift[]>()
    for (const s of shifts) {
      const k = `${s.employee_id}|${s.day}`
      m.set(k, [...(m.get(k) ?? []), s])
    }
    return m
  }, [shifts])

  const gapsByDay = days.map((d) => gaps.filter((g) => g.day === d))
  const show = (ev: React.MouseEvent, content: ReactNode) => setHover({ x: ev.clientX, y: ev.clientY, content })

  const shiftDetail = (e: Employee, s: Shift) => (
    <div className="space-y-1">
      <div className="font-semibold">{e.name}</div>
      <div className="text-ink-2">
        {fmtDayDate(schedule.week_start, s.day).weekday} {fmtRange(s.start, s.end)}, {fmtHours(paidHours(s))} paid,{' '}
        {fmtMoney(paidHours(s) * e.wage_per_hour)}
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
          {g.reasons.length} trained {g.reasons.length === 1 ? 'person' : 'people'} could not cover it. Details in Coverage.
        </div>
      )}
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
              <div>{rows.filter((r) => r.hours > 0).length} of {rows.length} scheduled</div>
              <div className="text-xs">Bars run {fmtRange(axisStart, axisEnd)}</div>
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
                  <div
                    className={`truncate text-xs ${dayGaps.length ? 'font-medium text-gap' : 'text-muted'}`}
                    title={dayGaps.length ? `${dayGaps.length} uncovered stretches, ${fmtMoney(cost)} penalty` : undefined}
                  >
                    {dayGaps.length ? `${fmtMoney(cost)} gaps` : closed ? 'Closed' : 'Covered'}
                  </div>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ e, hours }) => (
            <tr key={e.id} className="group">
              <th
                scope="row"
                className="border-b border-rule-soft bg-panel px-3 py-1.5 text-left font-normal group-hover:bg-paper"
              >
                <div className="truncate font-medium text-ink">{e.name}</div>
                <div className="text-xs text-muted">
                  {hours > 0 ? fmtHours(hours) : 'Off all week'}
                  {e.max_hours_week ? ` of ${fmtHours(e.max_hours_week)}` : ''}
                </div>
              </th>
              {days.map((d) => {
                const cell = byCell.get(`${e.id}|${d}`) ?? []
                return (
                  <td key={d} className="border-b border-l border-rule-soft px-1.5 py-1.5 align-middle group-hover:bg-paper">
                    {cell.map((s) => (
                      <div
                        key={s.id}
                        className="cursor-default"
                        onMouseMove={(ev) => show(ev, shiftDetail(e, s))}
                        onMouseLeave={() => setHover(null)}
                      >
                        <div className="relative h-3">
                          {s.segments.map((g, i) => (
                            <div
                              key={i}
                              className="absolute top-0 h-full first:rounded-l-sm last:rounded-r-sm"
                              style={{ left: pct(g.start), width: width(g.start, g.end), background: colors.get(g.role_id) }}
                            />
                          ))}
                        </div>
                        <div className="mt-0.5 truncate text-xs text-ink-2">{fmtRange(s.start, s.end)}</div>
                      </div>
                    ))}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
        <tfoot className="sticky bottom-0 z-10 bg-panel">
          <tr>
            <th className="border-t-2 border-gap/60 px-3 py-2 text-left font-semibold text-gap">Uncovered</th>
            {days.map((d) => (
              <td key={d} className="border-t-2 border-l border-t-gap/60 border-l-rule-soft px-1.5 py-2">
                <div className="relative h-3 rounded-sm bg-rule-soft">
                  {gapsByDay[d].map((g, i) => (
                    <div
                      key={i}
                      className="absolute top-0 h-full bg-gap"
                      style={{ left: pct(g.start), width: width(g.start, g.end), opacity: Math.min(1, 0.45 + 0.25 * g.missing_headcount) }}
                      onMouseMove={(ev) => show(ev, gapDetail(g))}
                      onMouseLeave={() => setHover(null)}
                    />
                  ))}
                </div>
              </td>
            ))}
          </tr>
        </tfoot>
      </table>

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
