import { useId, useMemo, useState } from 'react'
import type { DepartmentStaffingProps, DepartmentStaffingResult, RoleStaffing } from '../api/protocol'
import { fmtRange, fmtTime, WEEKDAY_NAMES } from '../lib/format'
import { roleColors } from '../lib/roles'
import { headcountRange, staffAt } from '../lib/staffing'
import { CardFrame, type CardProps } from './CardFrame'
import { fromHHMM, toHHMM } from './time'

const GROUP_LABEL: Record<string, string> = { weekday: 'Weekdays', saturday: 'Saturday', sunday: 'Sunday' }
const EMPTY: RoleStaffing = { base: 1, peaks: [], open: null, close: null }
const same = (a: RoleStaffing | undefined, b: RoleStaffing | undefined) => JSON.stringify(a) === JSON.stringify(b)

function describe(r: RoleStaffing): string {
  const parts = [`${r.base} most of the day`]
  for (const p of r.peaks) parts.push(`${p.headcount} ${GROUP_LABEL[p.day_group] ?? p.day_group} ${fmtRange(p.start, p.end)}`)
  if (r.open) parts.push(`${r.open.headcount} opening`)
  if (r.close) parts.push(`${r.close.headcount} closing`)
  return parts.join(' · ')
}

/** v1.3: per-department staffing questions with suggestions and a live preview. Replaces grid painting. */
export function DepartmentStaffingCard({ props, status, result, onSubmit, onCancel }: CardProps<DepartmentStaffingProps, DepartmentStaffingResult>) {
  const formId = useId()
  const p = props
  const roles = p?.roles ?? []
  const suggested = p?.suggested ?? {}
  const groups = p?.day_groups?.length ? p.day_groups : [{ id: 'weekday', days: [0, 1, 2, 3, 4] }]
  const [staff, setStaff] = useState<Record<string, RoleStaffing>>(() =>
    Object.fromEntries(roles.map((r) => [r.id, structuredClone(suggested[r.id] ?? EMPTY)])),
  )
  const [previewGroup, setPreviewGroup] = useState(groups[0]?.id ?? 'weekday')
  const colors = useMemo(() => roleColors(p?.roles ?? []), [p?.roles])
  const set = (rid: string, fn: (r: RoleStaffing) => RoleStaffing) => setStaff((s) => ({ ...s, [rid]: fn(structuredClone(s[rid])) }))
  const pre = p?.pre_open_minutes ?? 60
  const post = p?.post_close_minutes ?? 60
  const crewOptions = (max: number) => [15, 30, 45, 60, 90, 120, 180, 240].filter((m) => m <= Math.max(max, 15))

  const valid = Object.values(staff).every(
    (r) => r.base >= 0 && r.peaks.every((k) => k.end > k.start && k.headcount >= 0),
  )

  const deptName = p?.department?.name ?? 'Department'
  const shown = status === 'submitted' ? result?.staffing : undefined
  const summary = shown ? (
    <>
      {deptName}:{' '}
      {roles
        .filter((r) => shown[r.id])
        .map((r) => {
          const [lo, hi] = headcountRange(shown[r.id])
          return `${lo === hi ? lo : `${lo}–${hi}`} ${r.name}`
        })
        .join(', ')}
      .
    </>
  ) : null

  // Preview: first day of the selected group, 30-minute columns.
  const g = groups.find((x) => x.id === previewGroup) ?? groups[0]
  const hours = p?.hours?.find((h) => h.day === g?.days[0])
  const step = 30
  const lo = hours ? Math.floor((hours.open - Math.max(0, ...Object.values(staff).map((r) => r.open?.minutes_before_open ?? 0))) / 60) * 60 : 480
  const hi = hours ? Math.ceil((hours.close + Math.max(0, ...Object.values(staff).map((r) => r.close?.minutes_after_close ?? 0))) / 60) * 60 : 1320
  const times: number[] = []
  for (let t = lo; t < hi; t += step) times.push(t)

  return (
    <CardFrame
      title={`${deptName}: how many people?`}
      status={status}
      summary={summary}
      onCancel={onCancel}
      submitLabel="Save staffing"
      canSubmit={valid}
      formId={formId}
    >
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onSubmit({ staffing: staff })
        }}
        className="space-y-3"
      >
        <div className="flex items-start gap-2">
          <p className="flex-1 text-sm text-ink-2">
            I filled in suggestions. Change any number that's off, or accept them all. Trucks and events come later.
          </p>
          <button
            type="button"
            disabled={!valid}
            onClick={() => onSubmit({ staffing: staff })}
            className="shrink-0 rounded-md border border-pine bg-pine-wash px-2.5 py-1 text-sm font-semibold text-pine-dark hover:bg-pine hover:text-white disabled:opacity-50"
          >
            Looks right
          </button>
        </div>

        <div className="max-h-[26rem] space-y-2 overflow-y-auto pr-1">
          {roles.map((role) => {
            const r = staff[role.id]
            const sug = suggested[role.id]
            const isSug = same(r, sug)
            return (
              <fieldset key={role.id} className="rounded-md border border-rule p-2.5 text-sm">
                <legend className="sr-only">{role.name}</legend>
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="inline-block size-2.5 rounded-sm" style={{ background: colors.get(role.id) }} />
                  <span className="font-semibold">{role.name}</span>
                  {sug &&
                    (isSug ? (
                      <span className="ml-auto rounded bg-rule-soft px-1.5 text-[11px] text-ink-2">Suggested</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setStaff((s) => ({ ...s, [role.id]: structuredClone(sug) }))}
                        className="ml-auto text-[11px] font-semibold text-pine hover:underline"
                        title={`Suggested: ${describe(sug)}`}
                      >
                        Use suggestion
                      </button>
                    ))}
                </div>

                <Row>
                  <span className="w-28 text-ink-2">Most of the day</span>
                  <Num value={r.base} onChange={(n) => set(role.id, (x) => ({ ...x, base: n }))} label={`${role.name} most of the day`} />
                  <span className="text-muted">people</span>
                </Row>

                {r.peaks.map((k, i) => (
                  <div key={i} className="my-1 rounded bg-paper px-2 py-1.5">
                    <Row>
                      <span className="text-ink-2">Busy:</span>
                      <Num
                        value={k.headcount}
                        onChange={(n) => set(role.id, (x) => ((x.peaks[i].headcount = n), x))}
                        label={`${role.name} busy headcount`}
                      />
                      <span className="text-muted">on</span>
                      <select
                        aria-label="Days"
                        className="w-[6.5rem] rounded border border-rule bg-panel px-1 py-0.5"
                        value={k.day_group}
                        onChange={(e) => set(role.id, (x) => ((x.peaks[i].day_group = e.target.value), x))}
                      >
                        {groups.map((gr) => (
                          <option key={gr.id} value={gr.id}>
                            {GROUP_LABEL[gr.id] ?? gr.id}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        aria-label="Remove busy time"
                        className="ml-auto px-1 text-muted hover:text-gap"
                        onClick={() => set(role.id, (x) => ({ ...x, peaks: x.peaks.filter((_, j) => j !== i) }))}
                      >
                        ×
                      </button>
                    </Row>
                    <Row>
                      <Time value={k.start} onChange={(t) => set(role.id, (x) => ((x.peaks[i].start = t), x))} label="Busy from" />
                      <span className="text-muted">to</span>
                      <Time value={k.end} onChange={(t) => set(role.id, (x) => ((x.peaks[i].end = t), x))} label="Busy to" />
                      {k.end <= k.start && <span className="text-xs text-gap">Ends before it starts</span>}
                    </Row>
                  </div>
                ))}
                <Row>
                  <button
                    type="button"
                    className="text-xs font-semibold text-pine hover:underline"
                    onClick={() =>
                      set(role.id, (x) => ({
                        ...x,
                        peaks: [...x.peaks, { day_group: groups[0]?.id ?? 'weekday', start: 660, end: 840, headcount: x.base + 1 }],
                      }))
                    }
                  >
                    + {r.peaks.length ? 'Add another busy time' : 'Add a busy time'}
                  </button>
                </Row>

                <Row>
                  <label className="flex w-28 items-center gap-1.5 text-ink-2">
                    <input
                      type="checkbox"
                      checked={!!r.open}
                      onChange={(e) =>
                        set(role.id, (x) => ({ ...x, open: e.target.checked ? { headcount: 1, minutes_before_open: Math.min(60, pre) } : null }))
                      }
                    />
                    Opening crew
                  </label>
                  {r.open && (
                    <>
                      <Num value={r.open.headcount} onChange={(n) => set(role.id, (x) => ((x.open!.headcount = n), x))} label="Opening crew size" />
                      <span className="text-muted">starting</span>
                      <select
                        aria-label="Minutes before open"
                        className="rounded border border-rule px-1 py-0.5"
                        value={r.open.minutes_before_open}
                        onChange={(e) => set(role.id, (x) => ((x.open!.minutes_before_open = Number(e.target.value)), x))}
                      >
                        {[...new Set([...crewOptions(pre), r.open.minutes_before_open])].sort((a, b) => a - b).map((m) => (
                          <option key={m} value={m}>
                            {dur(m)}
                          </option>
                        ))}
                      </select>
                      <span className="text-muted">before open</span>
                    </>
                  )}
                </Row>
                <Row>
                  <label className="flex w-28 items-center gap-1.5 text-ink-2">
                    <input
                      type="checkbox"
                      checked={!!r.close}
                      onChange={(e) =>
                        set(role.id, (x) => ({ ...x, close: e.target.checked ? { headcount: 1, minutes_after_close: Math.min(30, post) } : null }))
                      }
                    />
                    Closing crew
                  </label>
                  {r.close && (
                    <>
                      <Num value={r.close.headcount} onChange={(n) => set(role.id, (x) => ((x.close!.headcount = n), x))} label="Closing crew size" />
                      <span className="text-muted">staying</span>
                      <select
                        aria-label="Minutes after close"
                        className="rounded border border-rule px-1 py-0.5"
                        value={r.close.minutes_after_close}
                        onChange={(e) => set(role.id, (x) => ((x.close!.minutes_after_close = Number(e.target.value)), x))}
                      >
                        {[...new Set([...crewOptions(post), r.close.minutes_after_close])].sort((a, b) => a - b).map((m) => (
                          <option key={m} value={m}>
                            {dur(m)}
                          </option>
                        ))}
                      </select>
                      <span className="text-muted">after close</span>
                    </>
                  )}
                </Row>
              </fieldset>
            )
          })}
        </div>

        <div>
          <div className="mb-1 flex items-center gap-1 text-xs">
            <span className="mr-1 font-semibold tracking-wide text-muted uppercase">Preview</span>
            {groups.map((gr) => (
              <button
                key={gr.id}
                type="button"
                aria-pressed={previewGroup === gr.id}
                onClick={() => setPreviewGroup(gr.id)}
                className={`rounded px-1.5 py-0.5 ${previewGroup === gr.id ? 'bg-ink text-white' : 'text-ink-2 hover:bg-paper'}`}
              >
                {GROUP_LABEL[gr.id] ?? gr.id}
              </button>
            ))}
            <span className="ml-auto text-muted">
              {g && g.days.length > 2 ? `${WEEKDAY_NAMES[g.days[0]]}–${WEEKDAY_NAMES[g.days.at(-1)!]}` : (g?.days ?? []).map((d) => WEEKDAY_NAMES[d]).join(', ')}
            </span>
          </div>
          {!hours ? (
            <p className="text-xs text-muted">Closed.</p>
          ) : (
            <table className="w-full table-fixed border-separate border-spacing-px text-[10px]">
              <colgroup>
                <col className="w-24" />
              </colgroup>
              <thead>
                <tr>
                  <th />
                  {times.map((t) => (
                    <th key={t} className="px-0 text-left font-normal text-muted">
                      {t % 180 === 0 ? <span className="block w-0 overflow-visible whitespace-nowrap">{fmtTime(t)}</span> : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {roles.map((role) => (
                  <tr key={role.id}>
                    <th scope="row" className="truncate pr-1 text-left font-normal text-ink-2">
                      {role.name}
                    </th>
                    {times.map((t) => {
                      const n = staffAt(staff[role.id], g?.id, hours, t + step / 2)
                      const inside = t >= hours.open && t < hours.close
                      return (
                        <td key={t} className="p-0" title={`${role.name} ${fmtRange(t, t + step)}: ${n}`}>
                          <span
                            className={`block h-4 text-center leading-4 ${n ? 'text-white' : inside ? 'bg-rule-soft' : 'bg-transparent'}`}
                            style={n ? { background: `rgb(11 93 79 / ${0.3 + Math.min(n, 6) * 0.12})` } : undefined}
                          >
                            {n > 1 ? n : ''}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </form>
    </CardFrame>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-1.5 py-0.5">{children}</div>
}

function Num({ value, onChange, label }: { value: number; onChange: (n: number) => void; label: string }) {
  return (
    <input
      type="number"
      min={0}
      max={50}
      aria-label={label}
      className="w-12 rounded border border-rule px-1 py-0.5 text-center tabular-nums"
      value={value}
      onChange={(e) => onChange(Math.max(0, Math.round(Number(e.target.value) || 0)))}
    />
  )
}

function Time({ value, onChange, label }: { value: number; onChange: (t: number) => void; label: string }) {
  return (
    <input
      type="time"
      step={900}
      aria-label={label}
      className="w-[6.25rem] rounded border border-rule bg-panel px-1 py-0.5 text-xs"
      value={toHHMM(value)}
      onChange={(e) => onChange(fromHHMM(e.target.value))}
    />
  )
}

function dur(m: number) {
  return m % 60 === 0 ? `${m / 60} h` : m > 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`
}
