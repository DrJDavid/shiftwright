import { useId, useState } from 'react'
import type { Department, Role } from '../contracts'
import type { RolesProps, RolesResult } from '../api/protocol'
import { CardFrame, inputCls, type CardProps } from './CardFrame'
import { slug, uniqueId } from './ids'

// API adds a plain-language priority per role (apps/api priorities.py); null = a custom $ value.
type Priority = 'must_cover' | 'important' | 'nice_to_have'
type RoleRow = Role & { priority?: Priority | null }
const PRIORITIES: { id: Priority; label: string }[] = [
  { id: 'must_cover', label: 'Must cover' },
  { id: 'important', label: 'Important' },
  { id: 'nice_to_have', label: 'Nice to have' },
]

export function RolesCard({ props, status, result, onSubmit, onCancel }: CardProps<RolesProps, RolesResult>) {
  const formId = useId()
  const [depts, setDepts] = useState<Department[]>(props?.departments ?? [])
  const [roles, setRoles] = useState<RoleRow[]>((props?.roles ?? []) as RoleRow[])
  const [newDept, setNewDept] = useState('')

  const setRole = (i: number, patch: Partial<RoleRow>) => setRoles((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRole = (department_id: string) =>
    setRoles((rs) => [
      ...rs,
      { id: uniqueId(rs.map((r) => r.id), 'new_role'), department_id, name: '', gap_penalty_per_hour: 0, min_age: 0, priority: 'important' },
    ])
  const addDept = () => {
    const name = newDept.trim()
    if (!name) return
    setDepts((ds) => [...ds, { id: uniqueId(ds.map((d) => d.id), slug(name)), name }])
    setNewDept('')
  }

  const valid = roles.length > 0 && roles.every((r) => r.name.trim() && (r.priority || r.gap_penalty_per_hour > 0))
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
    onSubmit({ departments: depts, roles: out as Role[] })
  }

  return (
    <CardFrame title="Departments and roles" status={status} summary={summary} onCancel={onCancel} submitLabel="Save roles" canSubmit={valid} formId={formId}>
      <form id={formId} onSubmit={submit} className="space-y-3">
        <p className="text-sm text-ink-2">
          Priority decides what stays covered if you run short on hours or people: Nice to have goes first, Must cover goes last.
        </p>
        <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
          {depts.map((d) => (
            <div key={d.id}>
              <div className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{d.name}</div>
              <div className="space-y-1">
                {roles.map((r, i) =>
                  r.department_id !== d.id ? null : (
                    <div key={i} className="grid grid-cols-[1fr_7.5rem_4rem_1rem] items-center gap-1.5 text-sm">
                      <input className={inputCls} value={r.name} placeholder="Role name" aria-label="Role name" onChange={(e) => setRole(i, { name: e.target.value })} />
                      <select
                        className={inputCls}
                        aria-label={`${r.name} priority`}
                        value={r.priority ?? 'custom'}
                        onChange={(e) => setRole(i, { priority: e.target.value === 'custom' ? null : (e.target.value as Priority) })}
                      >
                        {PRIORITIES.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                        {!r.priority &&
                          (r.gap_penalty_per_hour > 0 ? (
                            <option value="custom">Custom (${r.gap_penalty_per_hour}/h)</option>
                          ) : (
                            <option value="custom" disabled>
                              Pick…
                            </option>
                          ))}
                      </select>
                      <select className={inputCls} aria-label={`${r.name} minimum age`} value={r.min_age ?? 0} onChange={(e) => setRole(i, { min_age: Number(e.target.value) })}>
                        <option value={0}>Any</option>
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
