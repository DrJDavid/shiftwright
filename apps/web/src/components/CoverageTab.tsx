import { useMemo, useState } from 'react'
import type { SolveResponse } from '../api/protocol'
import type { Gap, StoreConfig } from '../contracts'
import { fmtDayDate, fmtMoney, fmtMoneyShort, fmtRange, fmtTime } from '../lib/format'
import { roleColors } from '../lib/roles'

type Props = {
  config: StoreConfig
  result: SolveResponse | null
  onGapClick: (g: Gap) => void
  day: number
  onDayChange: (d: number) => void
}

type Cell = { required: number; staffed: number; gaps: Gap[] }

/**
 * Role × time heatmap for one day. Required headcount comes from the store's demand, staffed from the
 * schedule's role segments, and red cells from the solver's own `gaps` (never recomputed here).
 */
export function CoverageTab({ config, result, onGapClick, day, onDayChange: setDay }: Props) {
  const [hover, setHover] = useState<{ x: number; y: number; role: string; t: number; cell: Cell } | null>(null)
  const colors = useMemo(() => roleColors(config.roles), [config.roles])
  const slot = config.store.slot_minutes ?? 30
  const schedule = result?.schedule

  const view = useMemo(() => {
    const demand = config.demand.filter((d) => d.day === day)
    const shifts = (schedule?.shifts ?? []).filter((s) => s.day === day)
    const gaps = (schedule?.gaps ?? []).filter((g) => g.day === day)
    const hours = config.store.hours.find((h) => h.day === day)
    const starts = [...demand.map((d) => d.start), ...shifts.map((s) => s.start), ...gaps.map((g) => g.start)]
    const ends = [...demand.map((d) => d.end), ...shifts.map((s) => s.end), ...gaps.map((g) => g.end)]
    if (hours) {
      starts.push(hours.open - (config.store.pre_open_minutes ?? 0))
      ends.push(hours.close + (config.store.post_close_minutes ?? 0))
    }
    if (starts.length === 0) return null
    const lo = Math.floor(Math.min(...starts) / slot) * slot
    const hi = Math.ceil(Math.max(...ends) / slot) * slot
    const times: number[] = []
    for (let t = lo; t < hi; t += slot) times.push(t)
    const roleIds = config.roles
      .map((r) => r.id)
      .filter((id) => demand.some((d) => d.role_id === id) || gaps.some((g) => g.role_id === id))
    const grid = new Map<string, Cell[]>()
    for (const id of roleIds) {
      grid.set(
        id,
        times.map((t) => {
          const mid = t + slot / 2
          const required = demand.filter((d) => d.role_id === id && d.start <= mid && mid < d.end).reduce((n, d) => n + d.headcount, 0)
          const staffed = shifts.filter((s) => s.segments.some((g) => g.role_id === id && g.start <= mid && mid < g.end)).length
          const cellGaps = gaps.filter((g) => g.role_id === id && g.start < t + slot && t < g.end)
          return { required, staffed, gaps: cellGaps }
        }),
      )
    }
    const dayCost = gaps.reduce((c, g) => c + g.penalty_dollars, 0)
    return { times, roleIds, grid, gapCount: gaps.length, dayCost }
  }, [config, schedule, day, slot])

  const roleName = (id: string) => config.roles.find((r) => r.id === id)?.name ?? id
  const weekStart = schedule?.week_start ?? config.store.week_start

  return (
    <div className="relative flex min-h-0 flex-1 flex-col" onMouseLeave={() => setHover(null)}>
      <div className="flex flex-wrap items-center gap-1 border-b border-rule px-3 py-2">
        {[0, 1, 2, 3, 4, 5, 6].map((d) => {
          const { weekday, date } = fmtDayDate(weekStart, d)
          const cost = (schedule?.gaps ?? []).filter((g) => g.day === d).reduce((c, g) => c + g.penalty_dollars, 0)
          return (
            <button
              key={d}
              type="button"
              onClick={() => setDay(d)}
              aria-pressed={day === d}
              className={`rounded-md border px-2.5 py-1 text-left text-sm ${
                day === d ? 'border-ink bg-ink text-white' : 'border-rule hover:border-ink'
              }`}
            >
              <span className="font-semibold">{weekday}</span> <span className={day === d ? 'text-white/70' : 'text-muted'}>{date.split(' ')[1]}</span>
              {schedule && (
                <span className={`block text-xs ${cost > 0 ? (day === d ? 'text-red-200' : 'text-gap') : day === d ? 'text-white/70' : 'text-muted'}`}>
                  {cost > 0 ? `${fmtMoneyShort(cost)} gaps` : 'Covered'}
                </span>
              )}
            </button>
          )
        })}
        <span className="ml-auto flex items-center gap-3 text-xs text-ink-2">
          <Legend cls="bg-pine/70" label="Covered" />
          <Legend cls="bg-gap" label="Gap" />
          <Legend cls="bg-rule-soft" label="No demand" />
        </span>
      </div>

      {!schedule && <p className="px-4 py-3 text-sm text-muted">Build the schedule to see coverage. Showing required headcount only.</p>}
      {!view || view.roleIds.length === 0 ? (
        <p className="p-6 text-muted">No demand on this day.</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto px-3 py-3">
          {view.gapCount > 0 && (
            <p className="mb-2 text-sm text-ink-2">
              {view.gapCount} uncovered {view.gapCount === 1 ? 'stretch' : 'stretches'}, {fmtMoney(view.dayCost)} gap cost. Click a red cell to see why.
            </p>
          )}
          <table className="w-full table-fixed border-separate border-spacing-px text-xs">
            <colgroup>
              <col className="w-36" />
            </colgroup>
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-panel" />
                {view.times.map((t) => (
                  <th key={t} className="px-0 text-left font-normal text-muted">
                    {t % 120 === 0 ? <span className="block w-0 overflow-visible whitespace-nowrap">{fmtTime(t)}</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.roleIds.map((id) => (
                <tr key={id}>
                  <th scope="row" className="sticky left-0 z-10 truncate bg-panel pr-2 text-left font-medium whitespace-nowrap text-ink">
                    <span className="mr-1.5 inline-block size-2.5 rounded-sm align-middle" style={{ background: colors.get(id) }} />
                    {roleName(id)}
                  </th>
                  {view.grid.get(id)!.map((c, i) => {
                    const t = view.times[i]
                    const isGap = c.gaps.length > 0
                    const bg = isGap ? 'bg-gap' : c.required > 0 ? 'bg-pine/70' : c.staffed > 0 ? 'bg-pine/25' : 'bg-rule-soft'
                    const Tag = isGap ? 'button' : 'div'
                    return (
                      <td key={t} className="p-0">
                        <Tag
                          {...(isGap ? { type: 'button' as const, onClick: () => onGapClick(c.gaps[0]) } : {})}
                          aria-label={isGap ? `${roleName(id)} ${fmtTime(t)} gap: why?` : undefined}
                          className={`block h-6 w-full ${bg} ${isGap ? 'cursor-pointer hover:outline-2 hover:outline-ink' : ''}`}
                          onMouseMove={(ev: React.MouseEvent) => setHover({ x: ev.clientX, y: ev.clientY, role: id, t, cell: c })}
                        >
                          {c.required > 1 && (
                            <span className={`block text-center text-[10px] leading-6 ${isGap || c.required > 0 ? 'text-white' : 'text-ink-2'}`}>
                              {c.required}
                            </span>
                          )}
                        </Tag>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">Numbers in cells are required headcount when more than one. Each column is {slot} minutes.</p>
        </div>
      )}

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-rule bg-panel px-3 py-2 text-sm shadow-lg"
          style={{ left: Math.min(hover.x + 14, window.innerWidth - 300), top: Math.min(hover.y + 14, window.innerHeight - 140) }}
        >
          <div className="font-semibold">
            {roleName(hover.role)}, {fmtRange(hover.t, hover.t + slot)}
          </div>
          <div className="text-ink-2">
            Need {hover.cell.required}, scheduled {hover.cell.staffed}
          </div>
          {hover.cell.gaps.map((g, i) => (
            <div key={i} className="text-gap">
              Gap {fmtRange(g.start, g.end)}: {g.missing_headcount} short, {fmtMoney(g.penalty_dollars)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block size-3 rounded-sm ${cls}`} />
      {label}
    </span>
  )
}
