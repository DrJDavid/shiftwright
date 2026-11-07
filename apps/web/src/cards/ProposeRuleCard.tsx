import { useId, useState } from 'react'
import type { ProposeRuleProps, ProposeRuleResult } from '../api/protocol'
import { STRENGTHS, strengthChoice, type StrengthChoice } from '../lib/strength'
import { CardFrame, type CardProps } from './CardFrame'

const toResult = (id: StrengthChoice): ProposeRuleResult => {
  const s = STRENGTHS.find((x) => x.id === id)!
  return s.decision === 'soft' ? { decision: 'soft', weight_dollars: s.weight } : { decision: s.decision }
}

const resultLabel = (r: ProposeRuleResult) =>
  r.decision === 'not_a_rule'
    ? 'Not a rule'
    : STRENGTHS.find((s) => s.id === strengthChoice({ strength: r.decision === 'hard' ? 'hard' : 'soft', weight_dollars: r.weight_dollars }))!.label

export function ProposeRuleCard({ props, status, result, onSubmit, onCancel }: CardProps<ProposeRuleProps, ProposeRuleResult>) {
  const formId = useId()
  const c = props?.constraint
  const suggested: StrengthChoice | null =
    props?.suggested === 'firm' ? 'firm' : props?.suggested === 'strong_preference' ? 'strong' : props?.suggested === 'preference' ? 'preference' : null
  // Preselect what their words said; they still press Save, and can pick anything else.
  const [choice, setChoice] = useState<StrengthChoice | null>(c?.status === 'confirmed' ? strengthChoice(c) : suggested)

  const summary = status === 'submitted' && result ? `${resultLabel(result)}.` : null

  return (
    <CardFrame title="Is this a rule?" status={status} summary={summary} onCancel={onCancel} submitLabel="Save" canSubmit={choice !== null} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (choice) onSubmit(toResult(choice))
        }}
        className="space-y-3"
      >
        <p className="text-base font-medium">{props?.plain_text || c?.note || c?.kind.replace(/_/g, ' ')}</p>
        {props?.evidence && (
          <p className="rounded-md bg-paper px-3 py-2 text-sm text-ink-2">
            <span className="font-semibold">Why I think so: </span>
            {props.evidence}
          </p>
        )}
        <div className="space-y-1.5" role="radiogroup" aria-label="How strict">
          {STRENGTHS.map((s) => (
            <label
              key={s.id}
              className={`flex cursor-pointer gap-2.5 rounded-md border px-3 py-2 text-sm ${choice === s.id ? 'border-pine bg-pine-wash' : 'border-rule hover:border-ink'}`}
            >
              <input type="radio" name={`${formId}-d`} checked={choice === s.id} onChange={() => setChoice(s.id)} className="mt-0.5" />
              <span>
                <span className="font-semibold">{s.label}</span>
                {s.id === suggested && <span className="ml-2 rounded bg-pine-wash px-1.5 py-0.5 text-[11px] font-semibold text-pine-dark">Suggested from what you said</span>}
                <span className="block text-xs text-muted">{s.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </form>
    </CardFrame>
  )
}
