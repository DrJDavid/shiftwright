import { useId, useState } from 'react'
import type { CoverageGridProps, CoverageGridResult, DayType } from '../api/protocol'
import { fmtRange, fmtTime, WEEKDAY_NAMES } from '../lib/format'
import { CardFrame, type CardProps } from './CardFrame'

const DAY_TYPE: Record<DayType, string> = { weekday: 'Weekdays', saturday: 'Saturday', sunday: 'Sunday', truck_day: 'Truck days', custom: 'Selected days' }
const BRUSHES = [0, 1, 2, 3, 4, 5]

/** Headcount per role per slot. Slot i covers [start_minute + i*slot, +slot) (API.md v1.1). Paint with a brush value. */
export function CoverageGridCard({ props, status, onSubmit, onCancel }: CardProps<CoverageGridProps, CoverageGridResult>) {
  const formId = useId()
  const p = props
  const slot = p?.slot_minutes ?? 30
  const start = p?.start_minute ?? 0
  const roles = (p?.roles ?? []).filter((r) => p?.prefill?.[r.id])
  const [grid, setGrid] = useState<Record<string, number[]>>(() => structuredClone(p?.prefill ?? {}))
  const [brush, setBrush] = useState(1)
  const [painting, setPainting] = useState(false)
  const readonly = p?.readonly === true
  const n = Math.max(0, ...Object.values(grid).map((v) => v.length))
  const days = (p?.days ?? []).map((d) => WEEKDAY_NAMES[d]).join(', ')
  // v1.5 custom: `days` is authoritative, so name the days themselves.
  const label = p?.day_type === 'custom' ? days || 'Selected days' : (DAY_TYPE[p?.day_type ?? 'weekday'] ?? p?.day_type)

  const paint = (rid: string, i: number) =>
    !readonly &&
    setGrid((g) => ({ ...g, [rid]: (g[rid] ?? []).map((v, j) => (j === i ? brush : v)) }))

  const hours = Object.values(grid).reduce((h, v) => h + v.reduce((a, b) => a + b, 0), 0) * (slot / 60)
  const summary = `${label} (${days || 'no days'}): ${Math.round(hours * 10) / 10} staff-hours per day.`

  return (
    <CardFrame title={`Coverage needs, ${label}`} status={status} summary={summary} onCancel={onCancel} submitLabel={readonly ? 'Looks right' : 'Save coverage'} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit({ prefill: grid })
        }}
        className="space-y-2"
        onMouseUp={() => setPainting(false)}
        onMouseLeave={() => setPainting(false)}
      >
        <p className="text-sm text-ink-2">
          Applies to {days || 'no open days'}. How many people each role needs, {fmtRange(start, start + n * slot)}.
          {readonly ? ' Preview only.' : ' Pick a number, then click or drag across cells.'}
        </p>
        <div className={`flex items-center gap-1 text-sm ${readonly ? 'hidden' : ''}`}>
          <span className="mr-1 text-muted">Brush</span>
          {BRUSHES.map((b) => (
            <button
              key={b}
              type="button"
              aria-pressed={brush === b}
              onClick={() => setBrush(b)}
              className={`size-7 rounded border font-semibold ${brush === b ? 'border-ink bg-ink text-white' : 'border-rule hover:border-ink'}`}
            >
              {b}
            </button>
          ))}
        </div>
        <div className="max-h-80 overflow-auto rounded border border-rule select-none">
          <table className="border-separate border-spacing-px text-[10px]">
            <thead className="sticky top-0 z-10 bg-panel">
              <tr>
                <th className="sticky left-0 z-20 bg-panel" />
                {Array.from({ length: n }, (_, i) => {
                  const t = start + i * slot
                  return (
                    <th key={i} className="w-4 min-w-4 text-left font-normal text-muted">
                      {t % 120 === 0 ? <span className="block w-0 overflow-visible whitespace-nowrap">{fmtTime(t)}</span> : null}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.id}>
                  <th scope="row" className="sticky left-0 z-10 max-w-28 truncate bg-panel pr-1.5 text-left text-xs font-normal">
                    {r.name}
                  </th>
                  {(grid[r.id] ?? []).map((v, i) => (
                    <td
                      key={i}
                      role="gridcell"
                      aria-label={`${r.name} ${fmtTime(start + i * slot)}: ${v}`}
                      className={`h-5 w-4 text-center ${readonly ? '' : 'cursor-pointer'} leading-5 ${v === 0 ? 'bg-rule-soft' : 'text-white'}`}
                      style={v > 0 ? { background: `rgb(11 93 79 / ${0.35 + Math.min(v, 5) * 0.13})` } : undefined}
                      onMouseDown={() => {
                        setPainting(true)
                        paint(r.id, i)
                      }}
                      onMouseEnter={() => painting && paint(r.id, i)}
                    >
                      {v > 0 ? v : ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </form>
    </CardFrame>
  )
}
