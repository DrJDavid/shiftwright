import { useId, useState, type ReactNode } from 'react'
import type { ConflictMenuProps, OptionResult, TradeoffProps } from '../api/protocol'
import { costLabel } from '../lib/format'
import { CardFrame, type CardProps } from './CardFrame'
import { useOptionalCardEnv } from './context'

type Opt = { id: string; label: string; cost_dollars: number; detail: string }

function OptionList({
  formId,
  title,
  intro,
  options,
  status,
  result,
  onSubmit,
  onCancel,
}: {
  formId: string
  title: string
  intro: ReactNode
  options: Opt[]
  status: CardProps<unknown, OptionResult>['status']
  result?: OptionResult
  onSubmit: (r: OptionResult) => void
  onCancel: () => void
}) {
  const [pick, setPick] = useState<string | null>(null)
  const chosen = options.find((o) => o.id === result?.option_id)
  const summary = status === 'submitted' && chosen ? `${chosen.label}${typeof chosen.cost_dollars === 'number' ? ` (${costLabel(chosen.cost_dollars)})` : ''}.` : null
  return (
    <CardFrame title={title} status={status} summary={summary} onCancel={onCancel} submitLabel="Choose" canSubmit={pick !== null} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (pick) onSubmit({ option_id: pick })
        }}
        className="space-y-2"
      >
        {intro}
        <div className="space-y-1.5" role="radiogroup">
          {options.map((o) => (
            <label
              key={o.id}
              className={`flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm ${pick === o.id ? 'border-pine bg-pine-wash' : 'border-rule hover:border-ink'}`}
            >
              <input type="radio" name={`${formId}-o`} checked={pick === o.id} onChange={() => setPick(o.id)} className="mt-0.5" />
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{o.label}</span>
                {o.detail && <span className="block text-xs text-ink-2">{o.detail}</span>}
              </span>
              <span className="shrink-0 font-semibold tabular-nums">{costLabel(o.cost_dollars)}</span>
            </label>
          ))}
        </div>
      </form>
    </CardFrame>
  )
}

export function TradeoffCard({ props, status, result, onSubmit, onCancel }: CardProps<TradeoffProps, OptionResult>) {
  const formId = useId()
  return (
    <OptionList
      formId={formId}
      title="Your call"
      intro={<p className="font-medium">{props?.question}</p>}
      options={(props?.options ?? []).map((o) => ({ ...o, detail: o.effect }))}
      status={status}
      result={result}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />
  )
}

export function ConflictMenuCard({ props, status, result, onSubmit, onCancel }: CardProps<ConflictMenuProps, OptionResult>) {
  const formId = useId()
  const inf = props?.infeasibility ?? {}
  const env = useOptionalCardEnv()
  const name = env?.ruleNames?.name ?? ((id: string) => id.replace(/_/g, ' '))
  const ids = [...(inf.conflicting_law_rule_ids ?? []), ...(inf.conflicting_constraint_ids ?? []), ...(inf.conflicting_other ?? [])]
  return (
    <OptionList
      formId={formId}
      title="These rules can't all be met"
      intro={
        <div className="rounded-md border border-gap/30 bg-gap-wash px-3 py-2 text-sm text-ink">
          {inf.summary ?? 'No legal schedule satisfies every hard rule.'}
          {ids.length > 0 && (
            <div className="mt-1 text-xs text-ink-2">
              Involved:
              <ul className="mt-0.5 list-disc pl-4">
                {ids.map((id) => (
                  <li key={id}>{name(id)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      }
      options={(props?.options ?? []).map((o) => ({ ...o, detail: o.patch_summary }))}
      status={status}
      result={result}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />
  )
}
