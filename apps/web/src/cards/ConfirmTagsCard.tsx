import { useId, useState } from 'react'
import type { ConfirmTagsProps, ConfirmTagsResult } from '../api/protocol'
import { tagLabel } from '../lib/vocab'
import { CardFrame, type CardProps } from './CardFrame'

type Decision = 'keep' | 'remove'

/** The owner keeps or removes the automatic protective tags on each role. Nothing is preselected. */
export function ConfirmTagsCard({ props, status, result, onSubmit, onCancel }: CardProps<ConfirmTagsProps, ConfirmTagsResult>) {
  const formId = useId()
  const roles = props?.roles ?? []
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const complete = roles.length > 0 && roles.every((r) => decisions[r.role_id])

  const summary =
    status === 'submitted' && result
      ? roles.map((r) => `${r.name}: ${result.decisions[r.role_id] === 'remove' ? 'tags removed' : 'tags kept'}`).join(' · ')
      : null

  return (
    <CardFrame title="Check the equipment tags" status={status} summary={summary} onCancel={onCancel} submitLabel="Save" canSubmit={complete} formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          if (complete) onSubmit({ decisions })
        }}
        className="space-y-3"
      >
        {props?.note && <p className="text-sm text-ink-2">{props.note}</p>}
        {roles.map((r) => (
          <fieldset key={r.role_id} className="rounded-md border border-rule px-3 py-2">
            <legend className="px-1 text-sm font-semibold">{r.name}</legend>
            <p className="text-sm text-ink-2">{r.tags.map(tagLabel).join(', ')}</p>
            {r.minors_trained.length > 0 && <p className="mt-0.5 text-sm font-medium text-warn">Minors trained here: {r.minors_trained.join(', ')}</p>}
            <div className="mt-1.5 flex gap-4 text-sm">
              {(['keep', 'remove'] as const).map((d) => (
                <label key={d} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name={`${formId}-${r.role_id}`}
                    checked={decisions[r.role_id] === d}
                    onChange={() => setDecisions((x) => ({ ...x, [r.role_id]: d }))}
                  />
                  {d === 'keep' ? 'Keep tags' : 'Remove tags'}
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </form>
    </CardFrame>
  )
}
