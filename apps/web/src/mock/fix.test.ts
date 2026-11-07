import { describe, expect, it } from 'vitest'
import { createApi } from '../api/client'
import type { OutreachState } from '../api/protocol'
import { createMockFetch } from './server'

describe('mock fix + outreach', () => {
  it('plans for a call-out, and a manual YES fills the slot and updates the schedule', async () => {
    const a = createApi(createMockFetch({ latencyMs: 0 }))
    const cfg = await a.createStore({ template: 'bigbox_mid', name: 'Store #0417', jurisdiction: { state: 'TX', city: 'austin' } })
    const { schedule } = await a.solve(cfg.store.id)
    const victim = (schedule.shifts ?? []).find((s) => s.day === 5)!
    const plan = await a.fix(cfg.store.id, { callouts: [{ employee_id: victim.employee_id, day: 5, reported_at: 364 }], day: 5, now: 364 })
    expect(plan.plan_id).toBeTruthy()
    expect(plan.outreach_queue.length).toBeGreaterThan(0)
    expect(plan.outreach_queue.every((c) => c.employee_id !== victim.employee_id)).toBe(true)
    expect(plan.coverage_after_best_pct).toBeGreaterThanOrEqual(plan.coverage_after_worst_pct)

    const started = await a.outreachStart(cfg.store.id, plan.plan_id!)
    expect(started.status).toBe('texting')
    const first = plan.outreach_queue[0]
    const phone = cfg.employees.find((e) => e.id === first.employee_id)!.phone
    const r = await a.mockReply(phone, 'Yes I can')
    expect(r.interpreted_as).toBe('accept')
    const st: OutreachState = await a.outreach(cfg.store.id)
    expect(st.accepted_employee_ids).toContain(first.employee_id)
    expect(st.schedule?.shifts?.some((s) => s.employee_id === first.employee_id && s.day === 5)).toBe(true)
    await a.outreachCancel(cfg.store.id)
  })

  it('fix before any schedule is a 409', async () => {
    const a = createApi(createMockFetch({ latencyMs: 0 }))
    const cfg = await a.createStore({ template: 'bigbox_mid', name: 'S', jurisdiction: { state: 'TX', city: null } })
    await expect(a.fix(cfg.store.id, { callouts: [], day: 5, now: 364 })).rejects.toMatchObject({ status: 409 })
  })
})
