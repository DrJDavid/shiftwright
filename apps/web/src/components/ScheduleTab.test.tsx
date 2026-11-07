// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { mockStoreConfig } from '../mock/fixture'
import { mockSolve } from '../mock/solver'
import type { Schedule } from '../contracts'
import { ScheduleTab } from './ScheduleTab'

afterEach(cleanup)

const cfg = mockStoreConfig('t', 'bigbox_small', 'S', 'TX', 'austin')

function tab(patch: Partial<Schedule>, onOpenChat = () => {}) {
  const { schedule, validation } = mockSolve(cfg)
  render(
    <ScheduleTab
      config={cfg}
      result={{ schedule: { ...schedule, ...patch }, validation }}
      solve={{ status: 'idle' }}
      onSolve={() => {}}
      onOpenChat={onOpenChat}
    />,
  )
}

const softV = (id: string) => ({ constraint_id: id, kind: 'fair_spread', amount: 1, penalty_dollars: 25, note: '' })

describe('Schedule header (C3)', () => {
  it('counts preferences not met instead of a dollar total', () => {
    tab({ soft_violations: [softV('c1'), softV('c2'), softV('c1')] })
    expect(screen.getByLabelText('Preferences not met: 3')).toBeTruthy()
    expect(screen.queryByText('Gap cost')).toBeNull()
  })

  it('shows 0 when every preference is met', () => {
    tab({ soft_violations: [] })
    expect(screen.getByLabelText('Preferences not met: 0')).toBeTruthy()
  })
})

describe('decisions waiting (C3 tradeoffs)', () => {
  it('links to the chat when the solver reports tradeoffs', () => {
    let opened = 0
    const t = { kind: 'budget_gap', day: 5, if_kept: {}, if_dropped: {} }
    tab({ solver_stats: { tradeoffs: [{ id: 'a', ...t }, { id: 'b', ...t }] } }, () => opened++)
    fireEvent.click(screen.getByRole('button', { name: '2 decisions waiting' }))
    expect(opened).toBe(1)
  })

  it('is absent with no tradeoffs', () => {
    tab({ solver_stats: { tradeoffs: [] } })
    expect(screen.queryByRole('button', { name: /decisions? waiting/ })).toBeNull()
  })

  it('the mock solve reports tradeoffs in the SEMANTICS #25 shape', () => {
    const { schedule } = mockSolve({ ...cfg, budget: { ...cfg.budget, weekly_hours_cap: 10 } })
    const ts = schedule.solver_stats!.tradeoffs as Record<string, unknown>[]
    expect(ts.length).toBeGreaterThan(0)
    expect(ts.length).toBeLessThanOrEqual(5)
    for (const t of ts) {
      expect(t).toMatchObject({ kind: 'budget_gap', day: expect.any(Number), extra_hours: expect.any(Number) })
      expect(Object.keys(t.if_kept as object).sort()).toEqual(['coverage_pct', 'hours', 'wage_cost'])
      expect(Object.keys(t.if_dropped as object).sort()).toEqual(['coverage_pct', 'hours', 'wage_cost'])
    }
  })
})
