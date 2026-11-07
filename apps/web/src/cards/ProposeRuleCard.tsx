import { useId, useState } from 'react'
import type { ProposeRuleProps, ProposeRuleResult } from '../api/protocol'
import { fmtMoney } from '../lib/format'
import { CardFrame, inputCls, type CardProps } from './CardFrame'

const CHOICES: { id: ProposeRuleResult['decision']; label: string; hint: string }[] = [
  { id: 'hard', label: 'Always', hint: 'A hard rule. The schedule never breaks it.' },
  { id: 'soft', label: 'Usually', hint: 'A preference with a price. Broken only when it saves more than that.' },
  { id: 'not_a_rule', label: 'Not a rule', hint: "Coincidence. Don't use it." },
]

export function ProposeRuleCard({ props, status, result, onSubmit, onCancel }: CardProps<ProposeRuleProps, ProposeRuleResult>) {
  const formId = useId()
  const c = props?.constraint
  const [decision, setDecision] = useState<ProposeRuleResult['decision'] | null>(
    c?.status === 'confirmed' ? c.strength : null,
  )
  const [weight, setWeight] = useState(c?.weight_dollars ? String(c.weight_dollars) : '')
  const w = Number(weight)
  const valid = decision === 'hard' || decision === 'not_a_rule' || (decision === 'soft' && weight.trim() !== '' && w > 0)

  const summary =
    status === 'submitted' && result
      ? result.decision === 'not_a_rule'
        ? 'Not a rule.'
        : result.decision === 'hard'
          ? 'Hard rule.'
          : `Soft rule, ${fmtMoney(result.weight_dollars ?? 0)} each time it's broken.`
      : null

  return (
    <CardFrame title="Is this a rule?" status={status} summary={summary} onCancel={onCancel} submitLabel="Save" canSubmit={valid} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid || !decision) return
          onSubmit(decision === 'soft' ? { decision, weight_dollars: w } : { decision })
        }}
        className="space-y-3"
      >
        <p className="text-base font-medium">{props?.plain_text || c?.note || c?.kind}</p>
        {props?.evidence && (
          <p className="rounded-md bg-paper px-3 py-2 text-sm text-ink-2">
            <span className="font-semibold">Why I think so: </span>
            {props.evidence}
          </p>
        )}
        <div className="space-y-1.5" role="radiogroup" aria-label="How strict">
          {CHOICES.map((ch) => (
            <label
              key={ch.id}
              className={`flex cursor-pointer gap-2.5 rounded-md border px-3 py-2 text-sm ${decision === ch.id ? 'border-pine bg-pine-wash' : 'border-rule hover:border-ink'}`}
            >
              <input type="radio" name={`${formId}-d`} checked={decision === ch.id} onChange={() => setDecision(ch.id)} className="mt-0.5" />
              <span>
                <span className="font-semibold">{ch.label}</span>
                <span className="block text-xs text-muted">{ch.hint}</span>
              </span>
            </label>
          ))}
        </div>
        {decision === 'soft' && (
          <label className="block text-sm">
            <span className="mb-1 block text-ink-2">What is it worth each time it's broken?</span>
            <div className="relative w-40">
              <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted">$</span>
              <input type="number" min={1} className={`${inputCls} pl-6`} value={weight} onChange={(e) => setWeight(e.target.value)} />
            </div>
          </label>
        )}
      </form>
    </CardFrame>
  )
}
