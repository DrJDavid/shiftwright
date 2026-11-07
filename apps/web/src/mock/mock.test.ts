import { describe, expect, it } from 'vitest'
import { createApi } from '../api/client'
import type { ChatEvent } from '../api/protocol'
import { createMockFetch } from './server'

function api() {
  return createApi(createMockFetch({ latencyMs: 0 }))
}

describe('mock API follows contracts/API.md', () => {
  it('solve returns a schedule whose metrics match its own shifts', async () => {
    const a = api()
    const cfg = await a.createStore({ template: 'bigbox_small', name: 'Store #0417', jurisdiction: { state: 'TX', city: 'austin' } })
    const { schedule, validation } = await a.solve(cfg.store.id)
    expect(schedule.shifts?.length).toBeGreaterThan(0)
    const paidHours = (schedule.shifts ?? []).reduce((h, s) => {
      const unpaid = (s.breaks ?? []).filter((b) => !b.paid).reduce((m, b) => m + b.end - b.start, 0)
      return h + (s.end - s.start - unpaid) / 60
    }, 0)
    expect(schedule.metrics?.total_hours).toBeCloseTo(paidHours, 5)
    expect(schedule.metrics!.budget_hours_used).toBeLessThanOrEqual(schedule.metrics!.budget_hours_cap)
    expect(validation?.hard_count).toBe(0)
  })

  it('seeds from the WS4 fixture and respects its min_age and min shift length', async () => {
    const a = api()
    const cfg = await a.createStore({ template: 'bigbox_small', name: 'Store #0417', jurisdiction: { state: 'TX', city: 'austin' } })
    expect(cfg.employees.map((e) => e.name)).toContain('Jordan Patel')
    const { schedule } = await a.solve(cfg.store.id)
    const age = new Map(cfg.employees.map((e) => [e.id, e.age]))
    const minAge = new Map(cfg.roles.map((r) => [r.id, r.min_age ?? 0]))
    for (const s of schedule.shifts ?? []) {
      expect(s.end - s.start).toBeGreaterThanOrEqual(240)
      for (const g of s.segments) expect(age.get(s.employee_id)!).toBeGreaterThanOrEqual(minAge.get(g.role_id)!)
    }
    expect(schedule.produced_by).toMatch(/^mock/)
  })

  it('chat turn pauses on a card and resumes after the card is submitted', async () => {
    const a = api()
    const cfg = await a.createStore({ template: 'bigbox_small', name: 'X', jurisdiction: { state: 'TX' } })
    const events: ChatEvent[] = []
    let submitted = false
    await a.chat(cfg.store.id, { mode: 'onboard', messages: [{ role: 'user', content: 'set up my store' }] }, (ev) => {
      events.push(ev)
      if (ev.event === 'card') {
        const result = ev.data.card_type === 'store_basics' ? { name: 'Store #0417' } : { weekly_hours_cap: 300 }
        void a.submitCard(cfg.store.id, { card_id: ev.data.card_id, result }).then(() => (submitted = true))
      }
    })
    const types = events.map((e) => e.event)
    expect(types).toContain('card')
    expect(types).toContain('config')
    expect(types.at(-1)).toBe('done')
    expect(submitted).toBe(true)
    const cards = events.flatMap((e) => (e.event === 'card' ? [e.data.card_type] : []))
    expect(cards).toEqual(['store_basics', 'payroll'])
    const after = await a.getConfig(cfg.store.id)
    expect(after.store.name).toBe('Store #0417')
    expect(after.budget.weekly_hours_cap).toBe(300)
  })
})
