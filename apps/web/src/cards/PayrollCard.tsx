import { useId, useState } from 'react'
import type { PayrollProps, PayrollResult } from '../api/protocol'
import { fmtHours, fmtMoney } from '../lib/format'
import { CardFrame, Field, inputCls, type CardProps } from './CardFrame'

export function PayrollCard({ props, status, result, onSubmit, onCancel }: CardProps<PayrollProps, PayrollResult>) {
  const formId = useId()
  const p = props ?? {}
  const [hours, setHours] = useState(p.weekly_hours_cap != null ? String(p.weekly_hours_cap) : '')
  const [dollars, setDollars] = useState(p.weekly_dollar_cap != null ? String(p.weekly_dollar_cap) : '')
  const [overtime, setOvertime] = useState(p.overtime_allowed ?? false)

  const h = Number(hours)
  const d = dollars.trim() === '' ? null : Number(dollars)
  const valid = hours.trim() !== '' && Number.isFinite(h) && h > 0 && (d === null || (Number.isFinite(d) && d > 0))

  const r = status === 'submitted' ? result : undefined
  const summary = r ? (
    <>
      {fmtHours(r.weekly_hours_cap)} weekly cap, {r.weekly_dollar_cap != null ? `${fmtMoney(r.weekly_dollar_cap)} dollar cap` : 'no dollar cap'},{' '}
      {r.overtime_allowed ? 'overtime allowed' : 'no overtime'}.
    </>
  ) : null

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!valid) return
    onSubmit({ ...p, weekly_hours_cap: h, weekly_dollar_cap: d, overtime_allowed: overtime, approvals: p.approvals ?? [] })
  }

  return (
    <CardFrame title="Payroll budget" status={status} summary={summary} onCancel={onCancel} submitLabel="Set budget" canSubmit={valid} formId={formId}>
      <form id={formId} onSubmit={submit} className="space-y-3">
        <p className="text-sm text-ink-2">
          The hours cap is a hard limit. The schedule will never go over it unless you approve extra hours.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Weekly hours cap" hint="From corporate's payroll allocation.">
            <div className="relative">
              <input type="number" min={1} step="0.5" inputMode="decimal" className={`${inputCls} pr-12`} value={hours} onChange={(e) => setHours(e.target.value)} required />
              <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-sm text-muted">hours</span>
            </div>
          </Field>
          <Field label="Weekly dollar cap" hint="Optional. Leave blank for none.">
            <div className="relative">
              <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-sm text-muted">$</span>
              <input type="number" min={1} step="1" inputMode="decimal" className={`${inputCls} pl-6`} value={dollars} onChange={(e) => setDollars(e.target.value)} />
            </div>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={overtime} onChange={(e) => setOvertime(e.target.checked)} />
          Allow overtime
        </label>
      </form>
    </CardFrame>
  )
}
