import { useState } from 'react'
import type { Check } from '../lib/setupSteps'

type Role = { id: string; name: string }

/** Role names the server tagged automatically, read from the equipment_roles check's detail. */
function autoTagged(detail: string, roles: Role[]) {
  const m = detail.match(/:\s*(.+?)\.\s*Please confirm/)
  if (!m) return []
  return m[1]
    // "Forklift (powered_industrial_truck); Fryer (fryer)" (readiness.py), or older "Forklift, Fryer".
    .split(/;\s|,\s(?![^()]*\))/)
    .map((part) => part.replace(/\s*\(.*\)$/, '').trim())
    .flatMap((n) => roles.filter((r) => r.name === n))
}

/** v1.4: "Is equipment" / "Not equipment" for roles the server tagged as powered equipment on its own. */
export function EquipmentReview({
  check,
  roles,
  onDecide,
}: {
  check: Check | undefined
  roles: Role[]
  onDecide: (roleId: string, decision: 'confirm' | 'reject') => Promise<void>
}) {
  const [deciding, setDeciding] = useState<string | null>(null)
  const pending = check ? autoTagged(check.detail, roles) : []
  if (!pending.length) return null
  const decide = (id: string, d: 'confirm' | 'reject') => {
    setDeciding(id)
    void onDecide(id, d).finally(() => setDeciding(null))
  }
  return (
    <div className="space-y-1">
      {pending.map((r) => (
        <div key={r.id} className="flex items-center gap-1.5 text-xs">
          <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
          <button
            type="button"
            disabled={!!deciding}
            onClick={() => decide(r.id, 'confirm')}
            className="rounded bg-pine px-1.5 py-0.5 font-semibold text-white disabled:opacity-50"
            title="Yes, this is powered equipment: under-18s can't work it"
          >
            Is equipment
          </button>
          <button
            type="button"
            disabled={!!deciding}
            onClick={() => decide(r.id, 'reject')}
            className="rounded border border-rule px-1.5 py-0.5 font-semibold text-ink-2 hover:border-ink disabled:opacity-50"
          >
            Not equipment
          </button>
        </div>
      ))}
    </div>
  )
}
