import { useId, useState } from 'react'
import type { Department, Role } from '../contracts'
import type { RolesProps, RolesResult } from '../api/protocol'
import { CardFrame, inputCls, type CardProps } from './CardFrame'
import { slug, uniqueId } from './ids'

export function RolesCard({ props, status, result, onSubmit, onCancel }: CardProps<RolesProps, RolesResult>) {
  const formId = useId()
  const [depts, setDepts] = useState<Department[]>(props?.departments ?? [])
  const [roles, setRoles] = useState<Role[]>(props?.roles ?? [])
  const [newDept, setNewDept] = useState('')

  const setRole = (i: number, patch: Partial<Role>) => setRoles((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRole = (department_id: string) =>
    setRoles((rs) => [
      ...rs,
      { id: uniqueId(rs.map((r) => r.id), 'new_role'), department_id, name: '', gap_penalty_per_hour: 15, min_age: 0 },
    ])
  const addDept = () => {
    const name = newDept.trim()
    if (!name) return
    setDepts((ds) => [...ds, { id: uniqueId(ds.map((d) => d.id), slug(name)), name }])
    setNewDept('')
  }

  const valid = roles.length > 0 && roles.every((r) => r.name.trim() && r.gap_penalty_per_hour >= 0)
  const shown = status === 'submitted' ? result : undefined
  const summary = shown ? `${shown.roles.length} roles in ${shown.departments.length} departments.` : null

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!valid) return
    const taken: string[] = []
    // New roles get an id from their name; existing ids never change.
    const out = roles.map((r) => {
      const fresh = r.id.startsWith('new_role')
      const id = fresh ? uniqueId([...taken, ...roles.filter((x) => !x.id.startsWith('new_role')).map((x) => x.id)], slug(r.name)) : r.id
      taken.push(id)
      return { ...r, id, name: r.name.trim() }
    })
    onSubmit({ departments: depts, roles: out })
  }

  return (
    <CardFrame title="Departments and roles" status={status} summary={summary} onCancel={onCancel} submitLabel="Save roles" canSubmit={valid} formId={formId}>
      <form id={formId} onSubmit={submit} className="space-y-3">
        <p className="text-sm text-ink-2">
          Gap cost is what an uncovered hour of the role is worth to you. The solver leaves the cheapest gaps first.
        </p>
        <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
          {depts.map((d) => (
            <div key={d.id}>
              <div className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{d.name}</div>
              <div className="space-y-1">
                {roles.map((r, i) =>
                  r.department_id !== d.id ? null : (
                    <div key={i} className="grid grid-cols-[1fr_5.5rem_4.5rem_1.5rem] items-center gap-1.5 text-sm">
                      <input className={inputCls} value={r.name} placeholder="Role name" aria-label="Role name" onChange={(e) => setRole(i, { name: e.target.value })} />
                      <label className="relative">
                        <span className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-xs text-muted">$</span>
                        <input
                          type="number"
                          min={0}
                          className={`${inputCls} pr-6 pl-4`}
                          aria-label={`${r.name} gap cost per hour`}
                          value={r.gap_penalty_per_hour}
                          onChange={(e) => setRole(i, { gap_penalty_per_hour: Number(e.target.value) })}
                        />
                        <span className="pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 text-xs text-muted">/h</span>
                      </label>
                      <select className={inputCls} aria-label={`${r.name} minimum age`} value={r.min_age ?? 0} onChange={(e) => setRole(i, { min_age: Number(e.target.value) })}>
                        <option value={0}>Any age</option>
                        <option value={16}>16+</option>
                        <option value={18}>18+</option>
                        <option value={21}>21+</option>
                      </select>
                      <button type="button" className="text-muted hover:text-gap" aria-label={`Remove ${r.name}`} onClick={() => setRoles((rs) => rs.filter((_, j) => j !== i))}>
                        ×
                      </button>
                    </div>
                  ),
                )}
                <button type="button" className="text-xs font-semibold text-pine hover:underline" onClick={() => addRole(d.id)}>
                  + Add role
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input className={inputCls} placeholder="New department" value={newDept} onChange={(e) => setNewDept(e.target.value)} />
          <button type="button" onClick={addDept} className="shrink-0 rounded-md border border-rule px-3 text-sm font-semibold hover:border-ink">
            Add
          </button>
        </div>
      </form>
    </CardFrame>
  )
}
