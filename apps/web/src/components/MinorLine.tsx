import type { MinorProtection } from '../lib/minors'
import { tagLabel } from '../lib/vocab'
import { shortLawName } from '../lib/ruleNames'

/** "Blake Allen, 15 — trained: Line Cook (Fryer, Cooking) — scheduled only as Server; barred by <rule> (<cite>)". */
export function MinorLine({ m, compact = false }: { m: MinorProtection; compact?: boolean }) {
  const trained = [...new Map(m.barred.flatMap((b) => b.roles).map((x) => [x.role.id, x])).values()]
  const tagsFor = (roleId: string) => [...new Set(m.barred.flatMap((b) => b.roles.filter((x) => x.role.id === roleId).flatMap((x) => x.tags)))]
  const scheduled = m.scheduledRoles.map((r) => r.name)
  return (
    <span className={compact ? 'text-xs' : 'text-[13px] print:text-[11px]'}>
      <span className="font-semibold">
        {m.employee.name}, {m.employee.age}
      </span>{' '}
      — trained: {trained.map((x) => `${x.role.name} (${tagsFor(x.role.id).map(tagLabel).join(', ')})`).join('; ')} —{' '}
      {m.workedBarred.length ? (
        <span className="font-semibold text-gap">scheduled in {m.workedBarred.map((r) => r.name).join(', ')}</span>
      ) : scheduled.length ? (
        <span className="text-pine-dark">scheduled only as {scheduled.join(', ')}</span>
      ) : (
        <span className="text-muted">not scheduled this week</span>
      )}
      ; barred by{' '}
      {m.barred.map((b, i) => (
        <span key={b.rule.id}>
          {i > 0 ? ', ' : ''}
          {shortLawName(b.rule)} (
          <a href={b.rule.citation?.url} target="_blank" rel="noreferrer" className="underline">
            {b.rule.citation?.title ?? 'source'}
          </a>
          )
        </span>
      ))}
      .
    </span>
  )
}
