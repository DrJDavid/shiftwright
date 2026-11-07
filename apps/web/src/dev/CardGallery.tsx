// DEV-ONLY (?gallery): every card with sample props from the WS4 demo fixture, for visual QA.
import { useState } from 'react'
import type { CardType } from '../api/protocol'
import { ChatCard } from '../cards'
import type { CardStatus } from '../cards/CardFrame'
import { CardEnvContext } from '../cards/context'
import { api } from '../api'
import { mockStoreConfig } from '../mock/fixture'
import { mockStaffingProps } from '../mock/staffing'

const cfg = mockStoreConfig('gallery', 'bigbox_mid', 'Store #0417', 'TX', 'austin')
const weekdayDemand = (roleId: string) => {
  const out = Array<number>(32).fill(0)
  for (const d of cfg.demand.filter((x) => x.day === 0 && x.role_id === roleId))
    for (let i = 0; i < 32; i++) {
      const t = 420 + i * 30
      if (d.start <= t && t < d.end) out[i] += d.headcount
    }
  return out
}

const SAMPLES: { type: CardType; props: unknown }[] = [
  { type: 'store_basics', props: cfg.store },
  { type: 'payroll', props: cfg.budget },
  { type: 'roles', props: { departments: cfg.departments, roles: cfg.roles } },
  { type: 'training_matrix', props: { employees: cfg.employees.slice(0, 12), roles: cfg.roles } },
  {
    type: 'coverage_grid',
    props: {
      day_type: 'weekday',
      days: [0, 2, 4],
      roles: cfg.roles,
      slot_minutes: 30,
      start_minute: 420,
      prefill: Object.fromEntries(cfg.roles.map((r) => [r.id, weekdayDemand(r.id)])),
    },
  },
  { type: 'department_staffing', props: mockStaffingProps(cfg, 'front_of_store') },
  {
    type: 'coverage_grid',
    props: {
      day_type: 'saturday',
      days: [5],
      roles: cfg.roles.slice(0, 4),
      slot_minutes: 30,
      start_minute: 420,
      readonly: true,
      prefill: Object.fromEntries(cfg.roles.slice(0, 4).map((r) => [r.id, weekdayDemand(r.id)])),
    },
  },
  { type: 'events', props: { events: cfg.events ?? [] } },
  { type: 'csv_import', props: { kind: 'roster' } },
  {
    type: 'propose_rule',
    props: {
      constraint: { ...(cfg.constraints ?? [])[8], status: 'provisional' },
      evidence: 'In 12 weeks of history, these two never closed on the same night.',
      plain_text: "Jordan and Casey shouldn't close together.",
    },
  },
  {
    type: 'tradeoff',
    props: {
      question: 'Saturday is 6 hours short on Cashier. Approve extra hours?',
      options: [
        { id: 'a', label: 'Approve 6 extra hours', cost_dollars: 87, effect: 'Covers the Saturday gap.' },
        { id: 'b', label: 'Leave the gap', cost_dollars: 0, effect: '$180 gap cost stays.' },
      ],
    },
  },
  {
    type: 'conflict_menu',
    props: {
      infeasibility: { summary: 'Leader on duty must be staffed 8a–10p, but only 2 leaders are available Sunday.', conflicting_constraint_ids: ['c_lod_always'] },
      options: [
        { id: 'x', label: 'Let a leader work 11 hours Sunday', cost_dollars: 45, patch_summary: 'max_shift_length 600 → 660 on Sunday' },
        { id: 'y', label: 'Allow a 2-hour gap without a leader', cost_dollars: 400, patch_summary: 'always_staffed becomes soft' },
      ],
    },
  },
  {
    type: 'employee_availability',
    props: {
      employee: { id: cfg.employees[0].id, name: cfg.employees[0].name },
      original_text: "can't do tuesdays, and no mornings on weekends pls",
      parsed: [
        { weekday: 1, start: 0, end: 1440, kind: 'unavailable', source: 'employee' },
        { weekday: 5, start: 0, end: 720, kind: 'unavailable', source: 'employee' },
        { weekday: 6, start: 0, end: 720, kind: 'unavailable', source: 'employee' },
      ],
    },
  },
]

export function CardGallery() {
  const [state, setState] = useState<Record<number, { status: CardStatus; result?: unknown }>>({})
  return (
    <CardEnvContext.Provider value={{ api, storeId: 'gallery', onConfigChanged: () => {} }}>
      <div className="h-full overflow-y-auto bg-paper p-6">
        <div className="mx-auto grid max-w-6xl grid-cols-3 items-start gap-4">
          {SAMPLES.map((s, i) => (
            <div key={i} data-card={s.type}>
              <div className="mb-1 text-xs text-muted">{s.type}</div>
              <ChatCard
                cardId={`g${i}`}
                cardType={s.type}
                props={s.props}
                status={state[i]?.status ?? 'open'}
                result={state[i]?.result}
                onSubmit={(r) => {
                  console.info('submit', s.type, JSON.stringify(r))
                  setState((x) => ({ ...x, [i]: { status: 'submitted', result: r } }))
                }}
                onCancel={() => setState((x) => ({ ...x, [i]: { status: 'cancelled' } }))}
              />
            </div>
          ))}
        </div>
      </div>
    </CardEnvContext.Provider>
  )
}
