import { useState } from 'react'
import type { Constraint, LawPack, LawRule, StoreConfig } from '../contracts'
import { fmtMoney, placeLabel } from '../lib/format'
import { describeConstraint } from '../lib/ruleNames'
import { tagLabel } from '../lib/vocab'

type Props = {
  config: StoreConfig
  lawPack: LawPack | null
  lawError: string | null
  /** Saves a status change for a provisional rule (full config PUT). */
  onSetStatus: (constraintId: string, status: 'confirmed' | 'rejected') => Promise<void>
}

type Group = { id: string; label: string; constraints: Constraint[] }

// Law-pack types that set pay rather than forbid a schedule.
const PRICED: LawRule['type'][] = ['weekly_overtime', 'daily_overtime', 'minimum_wage', 'reporting_time_pay', 'predictive_scheduling']

function lawStrength(r: LawRule): 'hard' | 'pay' {
  if (PRICED.includes(r.type)) return 'pay'
  if (r.type === 'min_rest_between_shifts' && r.params && (r.params as { premium_multiplier?: unknown }).premium_multiplier) return 'pay'
  return 'hard'
}

function levelLabel(r: LawRule) {
  if (r.level === 'federal') return 'Federal'
  if (r.level === 'city') return r.jurisdiction.city ? r.jurisdiction.city.replace(/\b\w/g, (c) => c.toUpperCase()) : 'City'
  return r.jurisdiction.state
}

const SOURCE_LABEL: Record<Constraint['source'], string> = {
  law: 'Law',
  corporate: 'Corporate',
  leader: 'You',
  inferred: 'From history',
  employee: 'Employee',
  default: 'Default',
}

/** Plain-language fallback when a rule has no note. Built only from the rule's own fields. */

export function Rulebook({ config, lawPack, lawError, onSetStatus }: Props) {
  const constraints = (config.constraints ?? []).filter((c) => c.status !== 'rejected')
  const rejected = (config.constraints ?? []).length - constraints.length
  const groups: Group[] = [
    { id: 'law', label: 'Law', constraints: constraints.filter((c) => c.source === 'law') },
    { id: 'corporate', label: 'Corporate', constraints: constraints.filter((c) => c.source === 'corporate') },
    {
      id: 'store',
      label: 'Store rules',
      constraints: constraints.filter((c) => c.source === 'leader' || c.source === 'inferred' || c.source === 'default'),
    },
    { id: 'employee', label: 'Employee preferences', constraints: constraints.filter((c) => c.source === 'employee') },
  ]
  const lawRules = lawPack?.rules ?? []
  const unmodeled = config.unmodeled ?? []

  return (
    <div className="space-y-4">
      <section>
        <GroupHeading
          label={`Labor rules for ${placeLabel(config.store.jurisdiction.city, config.store.jurisdiction.state)}`}
          count={lawRules.length + groups[0].constraints.length}
        />
        {lawError && <p className="text-xs text-gap">Couldn't load the labor rules: {lawError}</p>}
        {lawPack && lawPack.coverage !== 'full' && (
          <p className="mb-1.5 text-xs text-warn">
            {lawPack.coverage === 'state_only' ? 'City law not on file; state and federal only.' : 'State law not on file; federal only.'}
          </p>
        )}
        {(lawPack?.warnings ?? []).map((w, i) => (
          <p key={i} className="mb-1.5 text-xs text-warn">
            {w}
          </p>
        ))}
        <ul className="space-y-1">
          {lawRules.map((r) => (
            <LawLine key={r.id} rule={r} config={config} />
          ))}
          {groups[0].constraints.map((c) => (
            <RuleLine key={c.id} c={c} text={describeConstraint(c, config)} onSetStatus={onSetStatus} />
          ))}
        </ul>
        {!lawPack && !lawError && <p className="text-xs text-muted">Loading…</p>}
      </section>

      {groups.slice(1).map((g) => (
        <section key={g.id}>
          <GroupHeading label={g.label} count={g.constraints.length} />
          {g.constraints.length === 0 ? (
            <p className="text-xs text-muted">None yet.</p>
          ) : (
            <ul className="space-y-1">
              {g.constraints.map((c) => (
                <RuleLine key={c.id} c={c} text={describeConstraint(c, config)} onSetStatus={onSetStatus} />
              ))}
            </ul>
          )}
        </section>
      ))}

      <section>
        <GroupHeading label="Not modeled" count={unmodeled.length} />
        {unmodeled.length === 0 ? (
          <p className="text-xs text-muted">Nothing set aside.</p>
        ) : (
          <ul className="space-y-1.5">
            {unmodeled.map((u) => (
              <li key={u.id} className="text-sm">
                <span className="text-ink-2">{u.text}</span>
                <span className="block text-xs text-muted">{u.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {rejected > 0 && <p className="text-xs text-muted">{rejected} rejected {rejected === 1 ? 'rule' : 'rules'} hidden.</p>}
    </div>
  )
}

function GroupHeading({ label, count }: { label: string; count: number }) {
  return (
    <h3 className="mb-1.5 flex items-baseline justify-between text-xs font-semibold tracking-wide text-muted uppercase">
      {label}
      <span className="font-normal normal-case">{count}</span>
    </h3>
  )
}

function Badge({ kind, children }: { kind: 'hard' | 'soft' | 'pay'; children: React.ReactNode }) {
  const cls =
    kind === 'hard'
      ? 'border-ink/70 text-ink'
      : kind === 'soft'
        ? 'border-pine/50 text-pine-dark'
        : 'border-warn/50 text-warn'
  return <span className={`shrink-0 rounded border px-1 py-px text-[10px] leading-tight font-semibold ${cls}`}>{children}</span>
}

function LawLine({ rule, config }: { rule: LawRule; config: StoreConfig }) {
  const [open, setOpen] = useState(false)
  const strength = lawStrength(rule)
  const unverified = rule.verified === false || rule.confidence === 'low'
  return (
    <li className="text-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left hover:bg-paper"
      >
        <Badge kind={strength}>{strength === 'hard' ? 'Hard' : 'Pay'}</Badge>
        <span className="min-w-0 flex-1 text-ink-2">
          {rule.summary}
          {rule.type === 'minor_prohibited_roles' && <TaggedRoles rule={rule} config={config} />}
        </span>
        <span className="shrink-0 rounded bg-rule-soft px-1 text-[10px] leading-4 text-ink-2">{levelLabel(rule)}</span>
      </button>
      {open && (
        <div className="mt-1 ml-1 border-l-2 border-rule pl-2.5 text-xs text-ink-2">
          <a href={rule.citation.url} target="_blank" rel="noreferrer" className="font-medium text-pine-dark underline">
            {rule.citation.title}
          </a>
          {rule.citation.excerpt && <p className="mt-1 text-muted italic">"{rule.citation.excerpt}"</p>}
          <p className="mt-1 text-muted">
            Last checked {rule.citation.last_verified}
            {unverified ? ' · not yet verified by a person' : ''}
          </p>
        </div>
      )}
    </li>
  )
}

function RuleLine({
  c,
  text,
  onSetStatus,
}: {
  c: Constraint
  text: string
  onSetStatus: Props['onSetStatus']
}) {
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const provisional = c.status === 'provisional'
  const set = async (s: 'confirmed' | 'rejected') => {
    setSaving(true)
    try {
      await onSetStatus(c.id, s)
    } finally {
      setSaving(false)
    }
  }
  const hasDetail = Boolean(c.evidence || c.citation)
  return (
    <li className={`text-sm ${provisional ? 'rounded border border-dashed border-rule bg-paper/60 p-1' : ''}`}>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((o) => !o)}
        aria-expanded={hasDetail ? open : undefined}
        className={`flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left ${hasDetail ? 'hover:bg-paper' : 'cursor-default'}`}
      >
        <Badge kind={c.strength}>{c.strength === 'hard' ? 'Hard' : 'Soft'}</Badge>
        <span className={`min-w-0 flex-1 ${provisional ? 'text-muted' : 'text-ink-2'}`}>
          {text}
          {c.strength === 'soft' && c.weight_dollars ? (
            <span className="text-muted"> · {fmtMoney(c.weight_dollars)}</span>
          ) : null}
        </span>
        <span className="shrink-0 rounded bg-rule-soft px-1 text-[10px] leading-4 text-ink-2">{SOURCE_LABEL[c.source]}</span>
      </button>
      {open && (
        <div className="mt-1 ml-1 border-l-2 border-rule pl-2.5 text-xs text-ink-2">
          {c.evidence && <p>Why: {c.evidence}</p>}
          {c.citation && (
            <a href={c.citation.url} target="_blank" rel="noreferrer" className="font-medium text-pine-dark underline">
              {c.citation.title}
            </a>
          )}
        </div>
      )}
      {provisional && (
        <div className="mt-1 flex items-center gap-2 px-1 text-xs">
          <span className="text-muted">Unconfirmed</span>
          <button
            type="button"
            disabled={saving}
            onClick={() => void set('confirmed')}
            className="ml-auto rounded bg-pine px-2 py-0.5 font-semibold text-white disabled:opacity-50"
          >
            Confirm
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void set('rejected')}
            className="rounded border border-rule px-2 py-0.5 font-semibold text-ink-2 hover:border-ink disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </li>
  )
}

/** For hazardous-job rules: the tags it names and which of this store's roles carry them (v1.5 ROLE_TAGS). */
function TaggedRoles({ rule, config }: { rule: LawRule; config: StoreConfig }) {
  const p = (rule.params ?? {}) as { role_tags?: string[] }
  const tags = p.role_tags ?? []
  const byTag = (config.role_tags ?? {}) as Record<string, string[]>
  return (
    <span className="mt-0.5 flex flex-wrap gap-1">
      {tags.map((t) => {
        const roles = config.roles.filter((r) => (byTag[r.id] ?? []).includes(t))
        return (
          <span key={t} className="rounded bg-rule-soft px-1 text-[10px] text-ink-2" title={`Tag: ${t}`}>
            {tagLabel(t)}
            {roles.length ? `: ${roles.map((r) => r.name).join(', ')}` : ''}
          </span>
        )
      })}
    </span>
  )
}
