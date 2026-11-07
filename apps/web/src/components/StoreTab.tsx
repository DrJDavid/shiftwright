import { useMemo, useState, type ReactNode } from 'react'
import type { AvailabilityEntry, Employee, StoreConfig } from '../contracts'
import { fmtDayDate, fmtHours, fmtMoney, fmtRange, fmtTime, WEEKDAY_NAMES } from '../lib/format'
import { roleColors } from '../lib/roles'
import { eventName, SECTOR_LABEL, tagLabel } from '../lib/vocab'

type Section = 'people' | 'roles' | 'training' | 'demand' | 'availability' | 'budget'
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'people', label: 'People' },
  { id: 'roles', label: 'Roles' },
  { id: 'training', label: 'Training' },
  { id: 'demand', label: 'Demand' },
  { id: 'availability', label: 'Availability' },
  { id: 'budget', label: 'Budget & rules' },
]

type Props = { config: StoreConfig; onOpenRulebook: () => void }

/** Read-only review of everything the solver is given, in store-leader terms. Edits go through the chat. */
export function StoreTab({ config, onOpenRulebook }: Props) {
  const [section, setSection] = useState<Section>('people')
  const roleName = useMemo(() => new Map(config.roles.map((r) => [r.id, r.name])), [config.roles])
  const deptName = useMemo(() => new Map(config.departments.map((d) => [d.id, d.name])), [config.departments])
  const colors = useMemo(() => roleColors(config.roles), [config.roles])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-rule px-3 py-2">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-pressed={section === s.id}
            onClick={() => setSection(s.id)}
            className={`rounded-md px-2.5 py-1 text-sm font-semibold ${section === s.id ? 'bg-ink text-white' : 'text-ink-2 hover:bg-paper'}`}
          >
            {s.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted">Read-only. Change anything by telling the chat.</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {section === 'people' && <People config={config} roleName={roleName} deptName={deptName} />}
        {section === 'roles' && <Roles config={config} colors={colors} />}
        {section === 'training' && <Training config={config} deptName={deptName} />}
        {section === 'demand' && <Demand config={config} colors={colors} />}
        {section === 'availability' && <Availability config={config} />}
        {section === 'budget' && <Budget config={config} onOpenRulebook={onOpenRulebook} />}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ helpers

const STATUS: Record<Employee['status'], string> = { full_time: 'Full-time', part_time: 'Part-time', seasonal: 'Seasonal' }

function Th({ children, className = '', onClick, sorted }: { children?: ReactNode; className?: string; onClick?: () => void; sorted?: boolean }) {
  return (
    <th className={`sticky top-0 z-10 border-b border-rule bg-panel px-3 py-2 text-left text-xs font-semibold text-muted ${className}`}>
      {onClick ? (
        <button type="button" onClick={onClick} className={`hover:text-ink ${sorted ? 'text-ink' : ''}`}>
          {children}
          {sorted ? ' ▾' : ''}
        </button>
      ) : (
        children
      )}
    </th>
  )
}

function callinRecord(e: Employee): { text: string; tone: string } {
  const a = e.attendance
  if (!a || (a.shifts_90d ?? 0) === 0) return { text: 'No history', tone: 'text-muted' }
  const offered = a.callins_offered_90d ?? 0
  const accepted = a.callins_accepted_90d ?? 0
  const callouts = a.callouts_90d ?? 0
  const pick = offered ? `Took ${accepted} of ${offered}` : 'Never asked'
  return {
    text: `${pick} · ${callouts} out`,
    tone: callouts >= 4 ? 'text-warn' : 'text-ink-2',
  }
}

function tenure(hire: string): string {
  const d = new Date(`${hire}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return hire
  const years = (Date.now() - d.getTime()) / (365.25 * 864e5)
  return years >= 1 ? `${Math.floor(years)}y` : `${Math.max(1, Math.round(years * 12))}mo`
}

// ------------------------------------------------------------------ People

type SortKey = 'name' | 'dept' | 'wage' | 'age' | 'hire'

function People({ config, roleName, deptName }: { config: StoreConfig; roleName: Map<string, string>; deptName: Map<string, string> }) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<SortKey>('dept')
  const deptOrder = new Map(config.departments.map((d, i) => [d.id, i]))
  const rows = config.employees
    .filter((e) => {
      const n = q.trim().toLowerCase()
      return !n || e.name.toLowerCase().includes(n) || e.trained_role_ids.some((r) => (roleName.get(r) ?? r).toLowerCase().includes(n))
    })
    .sort((a, b) => {
      switch (sort) {
        case 'wage':
          return b.wage_per_hour - a.wage_per_hour
        case 'age':
          return a.age - b.age
        case 'hire':
          return a.hire_date.localeCompare(b.hire_date)
        case 'dept':
          return (deptOrder.get(a.home_department_id) ?? 99) - (deptOrder.get(b.home_department_id) ?? 99) || a.name.localeCompare(b.name)
        default:
          return a.name.localeCompare(b.name)
      }
    })
  const minors = config.employees.filter((e) => e.age < 18).length
  const ft = config.employees.filter((e) => e.status === 'full_time').length

  return (
    <div>
      <div className="flex items-center gap-4 px-4 py-2.5 text-sm">
        <input
          className="w-56 rounded-md border border-rule px-2.5 py-1.5 text-sm focus:border-pine focus:outline-none"
          placeholder="Find a person or role"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-ink-2">
          {config.employees.length} people · {ft} full-time · {minors} under 18
        </span>
      </div>
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <Th onClick={() => setSort('name')} sorted={sort === 'name'}>
              Name
            </Th>
            <Th onClick={() => setSort('dept')} sorted={sort === 'dept'}>
              Department
            </Th>
            <Th onClick={() => setSort('age')} sorted={sort === 'age'}>
              Age
            </Th>
            <Th>Status</Th>
            <Th onClick={() => setSort('wage')} sorted={sort === 'wage'} className="text-right">
              Wage
            </Th>
            <Th className="whitespace-nowrap">Hours/wk</Th>
            <Th>Trained for</Th>
            <Th className="whitespace-nowrap">Extra shifts (90d)</Th>
            <Th onClick={() => setSort('hire')} sorted={sort === 'hire'}>
              Tenure
            </Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const rec = callinRecord(e)
            return (
              <tr key={e.id} className="hover:bg-paper">
                <td className="border-b border-rule-soft px-3 py-1.5 font-medium whitespace-nowrap">{e.name}</td>
                <td className="border-b border-rule-soft px-3 py-1.5 whitespace-nowrap text-ink-2">{deptName.get(e.home_department_id) ?? e.home_department_id}</td>
                <td className="border-b border-rule-soft px-3 py-1.5 tabular-nums">
                  {e.age}
                  {e.age < 18 && <span className="ml-1.5 rounded bg-warn-wash px-1 text-[10px] font-semibold text-warn">Minor</span>}
                </td>
                <td className="border-b border-rule-soft px-3 py-1.5 whitespace-nowrap text-ink-2">{STATUS[e.status] ?? e.status}</td>
                <td className="border-b border-rule-soft px-3 py-1.5 text-right tabular-nums">
                  {fmtMoney(e.wage_per_hour, { cents: true })}
                  {e.tipped_wage_per_hour != null && (
                    <span className="block text-[11px] text-warn" title="Cash wage for shifts entirely in tipped roles">
                      {fmtMoney(e.tipped_wage_per_hour, { cents: true })} tipped
                    </span>
                  )}
                </td>
                <td className="border-b border-rule-soft px-3 py-1.5 whitespace-nowrap tabular-nums text-ink-2">
                  {e.min_hours_week ? `${e.min_hours_week}–` : 'up to '}
                  {e.max_hours_week != null ? fmtHours(e.max_hours_week) : '—'}
                </td>
                <td className="border-b border-rule-soft px-3 py-1.5 text-xs text-ink-2">
                  {e.trained_role_ids.length === 0 ? (
                    <span className="text-gap">Not trained yet</span>
                  ) : (
                    e.trained_role_ids.map((r) => roleName.get(r) ?? r).join(', ')
                  )}
                </td>
                <td
                  className={`border-b border-rule-soft px-3 py-1.5 text-xs whitespace-nowrap ${rec.tone}`}
                  title={`Last 90 days: ${e.attendance?.shifts_90d ?? 0} shifts, ${e.attendance?.callouts_90d ?? 0} call-outs, offered ${e.attendance?.callins_offered_90d ?? 0} extra shifts and took ${e.attendance?.callins_accepted_90d ?? 0}.`}
                >
                  {rec.text}
                </td>
                <td className="border-b border-rule-soft px-3 py-1.5 text-ink-2" title={`Hired ${e.hire_date}`}>
                  {tenure(e.hire_date)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------ Roles

function Roles({ config, colors }: { config: StoreConfig; colors: Map<string, string> }) {
  const tags = (config.role_tags ?? {}) as Record<string, string[]>
  return (
    <div className="grid grid-cols-2 gap-4 p-4">
      {config.departments.map((d) => {
        const roles = config.roles.filter((r) => r.department_id === d.id)
        const people = config.employees.filter((e) => e.home_department_id === d.id).length
        return (
          <section key={d.id} className="rounded-lg border border-rule">
            <h3 className="flex items-baseline justify-between border-b border-rule px-3 py-2 font-semibold">
              {d.name}
              <span className="text-xs font-normal text-muted">{people} people based here</span>
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted">
                  <th className="px-3 py-1 text-left font-medium">Role</th>
                  <th className="px-3 py-1 text-right font-medium">Gap cost</th>
                  <th className="px-3 py-1 text-left font-medium">Min age</th>
                  <th className="px-3 py-1 text-right font-medium">Trained</th>
                </tr>
              </thead>
              <tbody>
                {roles.map((r) => {
                  const trained = config.employees.filter((e) => e.trained_role_ids.includes(r.id)).length
                  return (
                    <tr key={r.id} className="border-t border-rule-soft">
                      <td className="px-3 py-1.5">
                        <span className="mr-1.5 inline-block size-2.5 rounded-sm" style={{ background: colors.get(r.id) }} />
                        {r.name}
                        {r.tipped && <span className="ml-1.5 rounded bg-warn-wash px-1 text-[10px] font-semibold text-warn">Tipped</span>}
                        {(tags[r.id] ?? []).map((t) => (
                          <span key={t} className="ml-1.5 rounded bg-rule-soft px-1 text-[10px] text-ink-2" title={`Tag: ${t}`}>
                            {tagLabel(t)}
                          </span>
                        ))}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(r.gap_penalty_per_hour)}/h</td>
                      <td className="px-3 py-1.5 text-ink-2">{r.min_age ? `${r.min_age}+` : 'Any'}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${trained === 0 ? 'font-semibold text-gap' : trained < 3 ? 'text-warn' : ''}`}>{trained}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        )
      })}
      <p className="col-span-2 text-xs text-muted">
        Gap cost is what one uncovered hour of the role is worth. The solver leaves a gap only when filling it costs more than this.
      </p>
    </div>
  )
}

// ------------------------------------------------------------------ Training

function Training({ config, deptName }: { config: StoreConfig; deptName: Map<string, string> }) {
  const order = new Map(config.departments.map((d, i) => [d.id, i]))
  const emps = [...config.employees].sort(
    (a, b) => (order.get(a.home_department_id) ?? 99) - (order.get(b.home_department_id) ?? 99) || a.name.localeCompare(b.name),
  )
  let lastDept = ''
  return (
    <table className="border-separate border-spacing-0 text-xs">
      <thead>
        <tr>
          <th className="sticky top-0 left-0 z-20 bg-panel" />
          {config.roles.map((r) => (
            <th key={r.id} className="sticky top-0 z-10 h-28 border-b border-rule bg-panel px-1 align-bottom font-medium text-ink-2">
              <span className="inline-block rotate-180 whitespace-nowrap [writing-mode:vertical-rl]">{r.name}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {emps.map((e) => {
          const header = e.home_department_id !== lastDept
          lastDept = e.home_department_id
          return [
            header && (
              <tr key={`h-${e.home_department_id}`}>
                <th
                  colSpan={config.roles.length + 1}
                  className="sticky left-0 border-b border-rule bg-paper px-3 py-1 text-left font-semibold tracking-wide text-ink-2 uppercase"
                >
                  {deptName.get(e.home_department_id) ?? e.home_department_id}
                </th>
              </tr>
            ),
            <tr key={e.id} className="hover:bg-paper">
              <th scope="row" className="sticky left-0 border-b border-rule-soft bg-panel px-3 py-1 text-left font-normal whitespace-nowrap">
                {e.name}
                {e.age < 18 && <span className="ml-1 text-warn">({e.age})</span>}
              </th>
              {config.roles.map((r) => (
                <td key={r.id} className="border-b border-l border-rule-soft text-center">
                  {e.trained_role_ids.includes(r.id) ? <span className="text-pine">●</span> : ''}
                </td>
              ))}
            </tr>,
          ]
        })}
        <tr>
          <th className="sticky left-0 bg-panel px-3 py-1.5 text-left font-semibold">Trained</th>
          {config.roles.map((r) => {
            const n = config.employees.filter((e) => e.trained_role_ids.includes(r.id)).length
            return (
              <td key={r.id} className={`text-center font-semibold tabular-nums ${n === 0 ? 'text-gap' : ''}`}>
                {n}
              </td>
            )
          })}
        </tr>
      </tbody>
    </table>
  )
}

// ------------------------------------------------------------------ Demand


function Demand({ config, colors }: { config: StoreConfig; colors: Map<string, string> }) {
  const [day, setDay] = useState(0)
  const slot = config.store.slot_minutes ?? 30
  const events = (config.events ?? []).filter((e) => e.day === day)
  const demand = config.demand.filter((d) => d.day === day)
  const dayHours = (d: number) =>
    config.demand.filter((x) => x.day === d).reduce((h, x) => h + (x.headcount * (x.end - x.start)) / 60, 0)
  const starts = [...demand.map((d) => d.start), ...events.map((e) => e.start)]
  const ends = [...demand.map((d) => d.end), ...events.map((e) => e.end)]
  const lo = starts.length ? Math.floor(Math.min(...starts) / 60) * 60 : 480
  const hi = ends.length ? Math.ceil(Math.max(...ends) / 60) * 60 : 1320
  const times: number[] = []
  for (let t = lo; t < hi; t += slot) times.push(t)
  const roleIds = config.roles.map((r) => r.id).filter((id) => demand.some((d) => d.role_id === id))
  const need = (rid: string, t: number) =>
    demand.filter((d) => d.role_id === rid && d.start <= t && t < d.end).reduce((n, d) => n + d.headcount, 0)
  const hours = config.store.hours.find((h) => h.day === day)

  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap gap-1">
        {WEEKDAY_NAMES.map((w, d) => {
          const evs = (config.events ?? []).filter((e) => e.day === d)
          return (
            <button
              key={w}
              type="button"
              aria-pressed={day === d}
              onClick={() => setDay(d)}
              className={`rounded-md border px-2.5 py-1 text-left text-sm ${day === d ? 'border-ink bg-ink text-white' : 'border-rule hover:border-ink'}`}
            >
              <span className="font-semibold">{w}</span> <span className={day === d ? 'text-white/70' : 'text-muted'}>{fmtDayDate(config.store.week_start, d).date.split(' ')[1]}</span>
              <span className={`block text-xs ${day === d ? 'text-white/70' : 'text-muted'}`}>
                {fmtHours(dayHours(d))}
                {evs.length ? ` · ${evs.map((e) => eventName(e)).join(', ')}` : ''}
              </span>
            </button>
          )
        })}
      </div>
      <p className="mb-2 text-sm text-ink-2">
        {hours ? `Open ${fmtRange(hours.open, hours.close)}.` : 'Closed.'} Staff-hours needed: {fmtHours(dayHours(day))}.
        {events.map((e) => (
          <span key={e.id} className="ml-2 rounded bg-warn-wash px-1.5 py-0.5 text-xs font-semibold text-warn">
            {eventName(e)} {fmtRange(e.start, e.end)}
            {e.note ? ` · ${e.note}` : ''}
          </span>
        ))}
      </p>
      {roleIds.length === 0 ? (
        <p className="text-muted">No demand set for this day.</p>
      ) : (
        <table className="w-full table-fixed border-separate border-spacing-px text-xs">
          <colgroup>
            <col className="w-36" />
          </colgroup>
          <thead>
            <tr>
              <th />
              {times.map((t) => (
                <th key={t} className="px-0 text-left font-normal text-muted">
                  {t % 120 === 0 ? <span className="block w-0 overflow-visible whitespace-nowrap">{fmtTime(t)}</span> : null}
                </th>
              ))}
            </tr>
            <tr>
              <th className="pr-2 text-left text-[10px] font-medium text-muted">Store open / events</th>
              {times.map((t) => {
                const open = hours && hours.open <= t && t < hours.close
                const ev = events.find((e) => e.start <= t && t < e.end)
                return (
                  <th key={t} className="p-0" title={ev ? `${eventName(ev)} ${fmtRange(ev.start, ev.end)}` : undefined}>
                    <span className={`block h-2 ${ev ? 'bg-warn' : open ? 'bg-ink/30' : 'bg-transparent'}`} />
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {roleIds.map((rid) => (
              <tr key={rid}>
                <th scope="row" className="truncate pr-2 text-left font-medium text-ink">
                  <span className="mr-1.5 inline-block size-2.5 rounded-sm align-middle" style={{ background: colors.get(rid) }} />
                  {config.roles.find((r) => r.id === rid)?.name ?? rid}
                </th>
                {times.map((t) => {
                  const n = need(rid, t)
                  const draft = demand.some((d) => d.role_id === rid && d.source === 'estimate' && d.start <= t && t < d.end)
                  return (
                    <td key={t} className="p-0" title={`${fmtRange(t, t + slot)}: ${n} needed${draft ? ' (draft estimate, not confirmed)' : ''}`}>
                      <span
                        className={`block h-6 text-center leading-6 ${n ? 'text-white' : 'bg-rule-soft'} ${draft ? 'outline-1 -outline-offset-2 outline-dashed outline-white/80' : ''}`}
                        style={n ? { background: `rgb(${draft ? '143 82 0' : '21 35 45'} / ${0.25 + Math.min(n, 6) * 0.12})` } : undefined}
                      >
                        {n || ''}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-xs text-muted">
        Each cell is how many people the role needs in that {slot}-minute slot.
        {config.demand.some((d) => d.source === 'estimate') && (
          <span className="ml-1 font-semibold text-warn">Amber dashed cells are a draft estimate: confirm them in the chat before relying on them.</span>
        )}
      </p>
    </div>
  )
}

// ------------------------------------------------------------------ Availability

const AV_KIND: Record<AvailabilityEntry['kind'], { label: string; cls: string }> = {
  unavailable: { label: "Can't work", cls: 'bg-gap-wash text-gap' },
  preferred_off: { label: 'Prefers off', cls: 'bg-warn-wash text-warn' },
  preferred_on: { label: 'Prefers to work', cls: 'bg-pine-wash text-pine-dark' },
}

function dayList(days: number[]): string {
  const ds = [...new Set(days)].sort((a, b) => a - b)
  const runs: string[] = []
  for (let i = 0; i < ds.length; ) {
    let j = i
    while (j + 1 < ds.length && ds[j + 1] === ds[j] + 1) j++
    runs.push(j - i >= 2 ? `${WEEKDAY_NAMES[ds[i]]}–${WEEKDAY_NAMES[ds[j]]}` : ds.slice(i, j + 1).map((d) => WEEKDAY_NAMES[d]).join(', '))
    i = j + 1
  }
  return runs.join(', ')
}

type AvLine = { kind: AvailabilityEntry['kind']; when: string; weight?: number; note?: string }

/** Same window/kind/note on several weekdays reads as one line: "Mon–Fri 12a–3p". */
function avLines(entries: AvailabilityEntry[]): AvLine[] {
  const groups = new Map<string, { e: AvailabilityEntry; days: number[] }>()
  const out: AvLine[] = []
  const span = (e: AvailabilityEntry) => (e.start <= 0 && e.end >= 1440 ? 'all day' : fmtRange(e.start, e.end))
  for (const e of entries) {
    if (e.on_date || e.weekday == null) {
      out.push({ kind: e.kind, when: `${e.on_date ?? 'Every day'}, ${span(e)}`, weight: e.weight_dollars, note: e.note })
      continue
    }
    const k = [e.kind, e.start, e.end, e.note ?? '', e.weight_dollars ?? ''].join('|')
    const g = groups.get(k)
    if (g) g.days.push(e.weekday)
    else groups.set(k, { e, days: [e.weekday] })
  }
  for (const { e, days } of groups.values())
    out.push({ kind: e.kind, when: `${dayList(days)}, ${span(e)}`, weight: e.weight_dollars, note: e.note })
  return out
}

function Availability({ config }: { config: StoreConfig }) {
  const withAv = config.employees.filter((e) => (e.availability ?? []).length > 0)
  const free = config.employees.length - withAv.length
  return (
    <div className="p-4">
      <p className="mb-3 text-sm text-ink-2">
        {withAv.length} people have limits or preferences. The other {free} can work any time the store needs them.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted">
            <th className="py-1 pr-3 text-left font-medium">Name</th>
            <th className="py-1 pr-3 text-left font-medium">Week</th>
            <th className="py-1 text-left font-medium">Details</th>
          </tr>
        </thead>
        <tbody>
          {withAv.map((e) => (
            <tr key={e.id} className="border-t border-rule-soft align-top">
              <td className="py-1.5 pr-3 font-medium whitespace-nowrap">
                {e.name}
                {e.age < 18 && <span className="ml-1 text-xs text-warn">({e.age})</span>}
              </td>
              <td className="py-1.5 pr-3">
                <WeekStrip entries={e.availability ?? []} />
              </td>
              <td className="py-1.5">
                <ul className="space-y-0.5">
                  {avLines(e.availability ?? []).map((a, i) => (
                    <li key={i}>
                      <span className={`mr-1.5 rounded px-1 text-[11px] font-semibold ${AV_KIND[a.kind].cls}`}>{AV_KIND[a.kind].label}</span>
                      {a.when}
                      {a.kind !== 'unavailable' && a.weight ? <span className="text-muted"> · {fmtMoney(a.weight)}</span> : null}
                      {a.note && <span className="text-muted"> · {a.note}</span>}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Seven small day boxes; each shows the strongest entry for that weekday (dated entries are listed only). */
function WeekStrip({ entries }: { entries: AvailabilityEntry[] }) {
  const rank = { unavailable: 3, preferred_off: 2, preferred_on: 1 } as const
  return (
    <div className="flex gap-0.5">
      {WEEKDAY_NAMES.map((w, d) => {
        const hits = entries.filter((a) => !a.on_date && (a.weekday == null || a.weekday === d))
        const top = hits.sort((a, b) => rank[b.kind] - rank[a.kind])[0]
        return (
          <span
            key={w}
            title={top ? `${w}: ${AV_KIND[top.kind].label}` : w}
            className={`flex size-5 items-center justify-center rounded-sm text-[9px] font-semibold ${top ? AV_KIND[top.kind].cls : 'bg-rule-soft text-muted'}`}
          >
            {w[0]}
          </span>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------ Budget & rules

function Budget({ config, onOpenRulebook }: { config: StoreConfig; onOpenRulebook: () => void }) {
  const b = config.budget
  const demandHours = config.demand.reduce((h, x) => h + (x.headcount * (x.end - x.start)) / 60, 0)
  const constraints = (config.constraints ?? []).filter((c) => c.status !== 'rejected')
  return (
    <div className="grid grid-cols-2 gap-4 p-4">
      <section className="rounded-lg border border-rule p-4">
        <h3 className="font-semibold">Payroll budget</h3>
        <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-ink-2">Weekly hours cap</dt>
          <dd className="text-right font-semibold tabular-nums">{b.weekly_hours_cap ? fmtHours(b.weekly_hours_cap) : 'Not set'}</dd>
          <dt className="text-ink-2">Weekly dollar cap</dt>
          <dd className="text-right tabular-nums">{b.weekly_dollar_cap != null ? fmtMoney(b.weekly_dollar_cap) : 'None'}</dd>
          <dt className="text-ink-2">Overtime</dt>
          <dd className="text-right">{b.overtime_allowed ? 'Allowed' : 'Not allowed'}</dd>
          <dt className="text-ink-2">Demand adds up to</dt>
          <dd className="text-right tabular-nums">{fmtHours(demandHours)} staff-hours</dd>
        </dl>
        {b.weekly_hours_cap > 0 && demandHours > b.weekly_hours_cap && (
          <p className="mt-2 text-sm text-warn">
            Demand is {fmtHours(demandHours - b.weekly_hours_cap)} more than the cap, so some gaps are expected. The solver picks which
            to leave by each role's gap cost.
          </p>
        )}
        {(b.approvals ?? []).length > 0 && (
          <div className="mt-3">
            <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">Approvals</h4>
            <ul className="mt-1 space-y-1 text-sm">
              {(b.approvals ?? []).map((a) => (
                <li key={a.id}>
                  +{fmtHours(a.extra_hours ?? 0)}
                  {a.extra_dollars ? ` / +${fmtMoney(a.extra_dollars)}` : ''} · {a.reason} ({a.approved_by})
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <section className="rounded-lg border border-rule p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="font-semibold">Rules</h3>
          <button type="button" onClick={onOpenRulebook} className="text-sm font-semibold text-pine hover:underline">
            Open the rulebook →
          </button>
        </div>
        <ul className="mt-2 space-y-1.5 text-sm">
          {constraints.map((c) => (
            <li key={c.id} className="flex gap-2">
              <span className={`shrink-0 rounded border px-1 text-[10px] leading-4 font-semibold ${c.strength === 'hard' ? 'border-ink/70' : 'border-pine/50 text-pine-dark'}`}>
                {c.strength === 'hard' ? 'Hard' : 'Soft'}
              </span>
              <span className={c.status === 'provisional' ? 'text-muted' : 'text-ink-2'}>
                {c.note || c.kind}
                {c.strength === 'soft' && c.weight_dollars ? <span className="text-muted"> · {fmtMoney(c.weight_dollars)}</span> : null}
                {c.status === 'provisional' && <span className="text-warn"> · unconfirmed</span>}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">Labor law for {config.store.jurisdiction.state} is listed in the rulebook with citations.</p>
      </section>
      <section className="col-span-2 rounded-lg border border-rule p-4 text-sm">
        <h3 className="font-semibold">Business and hours</h3>
        <p className="mt-1 text-ink-2">
          {config.store.sector ? SECTOR_LABEL[config.store.sector] : 'Business type not set (all sector-specific laws are applied)'}
          {config.store.business_description ? ` · ${config.store.business_description}` : ''}
        </p>
        <div className="mt-2 grid grid-cols-7 gap-2">
          {WEEKDAY_NAMES.map((w, d) => {
            const h = config.store.hours.find((x) => x.day === d)
            return (
              <div key={w} className="rounded-md bg-paper px-2 py-1.5">
                <div className="font-semibold">{w}</div>
                <div className="text-ink-2">{h ? fmtRange(h.open, h.close) : 'Closed'}</div>
              </div>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-muted">
          Staff can start up to {fmtMinutes(config.store.pre_open_minutes ?? 0)} before open and stay {fmtMinutes(config.store.post_close_minutes ?? 0)} after
          close.
          Schedules use {config.store.slot_minutes}-minute slots.{' '}
          {(config.store.max_shifts_per_day ?? 1) > 1
            ? `Split shifts allowed: up to ${config.store.max_shifts_per_day} shifts per person per day.`
            : 'One shift per person per day (no split shifts).'}
        </p>
      </section>
    </div>
  )
}

function fmtMinutes(m: number): string {
  if (m % 60 === 0) return `${m / 60} hour${m === 60 ? '' : 's'}`
  return `${m} minutes`
}
