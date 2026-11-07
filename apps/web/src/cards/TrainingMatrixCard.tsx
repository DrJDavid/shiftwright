import { useId, useState } from 'react'
import type { TrainingMatrixProps, TrainingMatrixResult } from '../api/protocol'
import { CardFrame, inputCls, type CardProps } from './CardFrame'

export function TrainingMatrixCard({ props, status, result, onSubmit, onCancel }: CardProps<TrainingMatrixProps, TrainingMatrixResult>) {
  const formId = useId()
  const employees = props?.employees ?? []
  const roles = props?.roles ?? []
  const [m, setM] = useState<TrainingMatrixResult>(() => Object.fromEntries(employees.map((e) => [e.id, e.trained_role_ids ?? []])))
  const [filter, setFilter] = useState('')

  const toggle = (eid: string, rid: string) =>
    setM((x) => {
      const cur = x[eid] ?? []
      return { ...x, [eid]: cur.includes(rid) ? cur.filter((r) => r !== rid) : [...cur, rid] }
    })
  const shownEmps = employees.filter((e) => e.name.toLowerCase().includes(filter.trim().toLowerCase()))
  const untrained = roles.filter((r) => !Object.values(m).some((ids) => ids.includes(r.id)))

  const done = status === 'submitted' && result
  const summary = done ? `Training saved for ${Object.keys(result).length} people.` : null

  return (
    <CardFrame title="Who is trained for what" status={status} summary={summary} onCancel={onCancel} submitLabel="Save training" formId={formId}>
      <form
        id={formId}
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit(m)
        }}
        className="space-y-2"
      >
        <input className={inputCls} placeholder="Find a person" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find a person" />
        <div className="max-h-80 overflow-auto rounded border border-rule">
          <table className="border-separate border-spacing-0 text-xs">
            <thead className="sticky top-0 z-10 bg-panel">
              <tr>
                <th className="sticky left-0 z-20 bg-panel" />
                {roles.map((r) => (
                  <th key={r.id} className="h-24 border-b border-rule px-0.5 align-bottom font-medium text-ink-2" title={r.name}>
                    <span className="inline-block max-h-24 truncate [writing-mode:vertical-rl] rotate-180">{r.name}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shownEmps.map((e) => (
                <tr key={e.id} className="hover:bg-paper">
                  <th scope="row" className="sticky left-0 max-w-28 truncate border-b border-rule-soft bg-panel px-2 py-0.5 text-left font-normal">
                    {e.name}
                  </th>
                  {roles.map((r) => (
                    <td key={r.id} className="border-b border-rule-soft px-0.5 text-center">
                      <input
                        type="checkbox"
                        aria-label={`${e.name} trained for ${r.name}`}
                        checked={(m[e.id] ?? []).includes(r.id)}
                        onChange={() => toggle(e.id, r.id)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {untrained.length > 0 && (
          <p className="text-xs text-warn">Nobody trained yet for: {untrained.map((r) => r.name).join(', ')}.</p>
        )}
      </form>
    </CardFrame>
  )
}
