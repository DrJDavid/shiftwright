import { useMemo } from 'react'
import type { Schedule, StoreConfig } from '../contracts'
import { capacity, type Cause } from '../lib/capacity'
import { fmtHours } from '../lib/format'

const WHY: Record<Cause, string> = {
  max_hours: 'the people trained for those roles are at their max hours',
  availability: "nobody trained for those roles is available then",
  budget: 'of your hours budget (see the decisions)',
  training: 'too few people are trained for those roles',
  rules: 'labor rules or your own rules keep people off those times',
  busy: 'the people trained for those roles are already working other roles then',
  short_window: "those windows are shorter than a minimum shift, so covering them would cost more than leaving them",
}

const FIX: Partial<Record<Cause | 'capacity', (role: string) => string>> = {
  capacity: (role) => `To cover it: raise someone's max hours, train more people for ${role}, or hire.`,
  max_hours: (role) => `To cover it: raise someone's max hours or train more people for ${role}.`,
  availability: (role) => `To cover it: ask who could work those times, or train more people for ${role}.`,
  training: (role) => `To cover it: train more people for ${role}.`,
  busy: (role) => `To cover it: train more people for ${role}.`,
}

/** Under the schedule stats: why the week has gaps, in plain words, from the engine's gap reasons. Says
 *  when the team itself (everyone's max hours) is the limit, so unused budget doesn't look like waste. */
export function CapacityNote({ config, schedule }: { config: StoreConfig; schedule: Schedule }) {
  const c = useMemo(() => capacity(config, schedule), [config, schedule])
  if (c.gapHours < 0.25) return null
  const cap = schedule.metrics?.budget_hours_cap ?? config.budget.weekly_hours_cap
  const used = schedule.metrics?.budget_hours_used ?? 0
  const teamShort = c.maxHours < c.neededHours
  const budgetLeft = cap - used >= 1
  const top = c.roles[0]
  const fix = (teamShort ? FIX.capacity : c.mainCause ? FIX[c.mainCause] : undefined)?.(top?.name ?? 'those roles')

  return (
    <div className="border-b border-warn/30 bg-warn-wash px-4 py-2.5 text-sm" role="note" aria-label="Why there are gaps">
      <p>
        <span className="font-semibold">{fmtHours(c.gapHours)} uncovered. </span>
        {teamShort ? (
          <>
            Your team can work at most <span className="font-semibold">{fmtHours(c.maxHours)}</span> this week (everyone's max hours added up), but
            staffing needs <span className="font-semibold">{fmtHours(c.neededHours)}</span>.
          </>
        ) : (
          c.mainCause && <>Mostly because {WHY[c.mainCause]}.</>
        )}
        {!budgetLeft && c.mainCause !== 'budget' && <span className="text-ink-2"> The hours budget is also fully used.</span>}
        {budgetLeft && c.mainCause !== 'budget' && (
          <span className="text-ink-2"> The budget isn't the limit: {fmtHours(cap - used)} of it is unused because nobody who could fill these gaps has hours left.</span>
        )}
      </p>
      {c.roles.length > 0 && (
        <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-ink-2">
          {c.roles.slice(0, 4).map((r) => (
            <li key={r.roleId}>
              <span className="font-medium text-ink">{r.name}</span> {fmtHours(r.gapHours)} short · {r.trained} trained
              {r.atMax > 0 && `, ${r.atMax === r.trained ? 'all' : r.atMax} at their max`}
            </li>
          ))}
        </ul>
      )}
      {fix && <p className="mt-1 text-ink-2">{fix}</p>}
    </div>
  )
}
