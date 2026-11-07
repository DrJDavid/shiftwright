// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { ApiError, type Api } from '../api/client'
import { BuildProgressLine } from '../components/BuildProgressLine'
import { ScheduleStats } from '../components/ScheduleStats'
import { mockStoreConfig } from '../mock/fixture'
import { mockSolve } from '../mock/solver'
import { progressMessage, stopReasonLine } from './buildProgress'
import { useSolveProgress } from './useSolveProgress'

afterEach(cleanup)

describe('progress line (C4)', () => {
  it('counts seconds, then says it is still improving after ~10 s', () => {
    expect(progressMessage(3.7)).toBe('Building your week… 3 s')
    expect(progressMessage(9.9)).toBe('Building your week… 9 s')
    expect(progressMessage(12.2)).toBe('Still improving — stops when the schedule stops getting better (max 90 s) · 12 s')
  })

  it('renders coverage so far only when the server reports it', () => {
    render(<BuildProgressLine startedAt={Date.now() - 12_000} coveragePct={93} />)
    expect(screen.getByRole('status').textContent).toMatch(/^Still improving/)
    expect(screen.getByText('Coverage so far: 93%')).toBeTruthy()
    cleanup()
    render(<BuildProgressLine startedAt={Date.now()} />)
    expect(screen.getByRole('status').textContent).toBe('Building your week… 0 s')
    expect(screen.queryByText(/Coverage so far/)).toBeNull()
  })
})

describe('stop reason wording (C4)', () => {
  it('words each stop_reason with the seconds taken', () => {
    expect(stopReasonLine({ stop_reason: 'proven_close', total_s: 14.4 })).toBe('Best schedule found (within 1% of the best possible) · 14 s')
    expect(stopReasonLine({ stop_reason: 'plateau', total_s: 31.6 })).toBe('Stopped when it stopped improving · 32 s')
    expect(stopReasonLine({ stop_reason: 'cap', total_s: 90.2 })).toBe('Stopped at the 90 s limit · 90 s')
    expect(stopReasonLine({ stop_reason: 'plateau' })).toBe('Stopped when it stopped improving')
  })

  it('says nothing for time_limit, unknown or missing reasons', () => {
    expect(stopReasonLine({ stop_reason: 'time_limit', total_s: 20 })).toBeNull()
    expect(stopReasonLine({ stop_reason: 'whatever' })).toBeNull()
    expect(stopReasonLine({})).toBeNull()
    expect(stopReasonLine(undefined)).toBeNull()
  })

  it('shows the line under the schedule stats', () => {
    const cfg = mockStoreConfig('t', 'bigbox_small', 'S', 'TX', 'austin')
    const { schedule, validation } = mockSolve(cfg)
    render(
      <ScheduleStats
        schedule={{ ...schedule, solver_stats: { stop_reason: 'proven_close', total_s: 14 } }}
        validation={validation}
        employeeName={(id) => id}
        demand={cfg.demand}
      />,
    )
    expect(screen.getByText('Best schedule found (within 1% of the best possible) · 14 s')).toBeTruthy()
  })
})

function fakeApi(respond: () => Promise<unknown>) {
  let calls = 0
  const api = {
    solveProgress: () => {
      calls++
      return respond()
    },
  } as unknown as Api
  return { api, calls: () => calls }
}

describe('progress polling is feature-detected (C4)', () => {
  it('polls while running when the endpoint answers, and reports coverage', async () => {
    const f = fakeApi(async () => ({ running: true, elapsed_s: 3, coverage_pct: 91 }))
    const { result, rerender } = renderHook(({ running }) => useSolveProgress(f.api, 's1', running, 20), { initialProps: { running: true } })
    await waitFor(() => expect(result.current).toBe(91))
    await waitFor(() => expect(f.calls()).toBeGreaterThanOrEqual(3))
    rerender({ running: false })
    const n = f.calls()
    await new Promise((r) => setTimeout(r, 80))
    expect(f.calls()).toBe(n)
    expect(result.current).toBeNull()
  })

  it('asks once, and never again after a 404', async () => {
    const f = fakeApi(async () => {
      throw new ApiError(404, 'Not Found')
    })
    const { result, rerender } = renderHook(({ running }) => useSolveProgress(f.api, 's1', running, 20), { initialProps: { running: true } })
    await waitFor(() => expect(f.calls()).toBe(1))
    await new Promise((r) => setTimeout(r, 80))
    expect(f.calls()).toBe(1)
    rerender({ running: false })
    rerender({ running: true })
    await new Promise((r) => setTimeout(r, 80))
    expect(f.calls()).toBe(1)
    expect(result.current).toBeNull()
  })

  it('does not poll when no build is running', async () => {
    const f = fakeApi(async () => ({ running: false, elapsed_s: 0 }))
    renderHook(() => useSolveProgress(f.api, 's1', false, 20))
    await new Promise((r) => setTimeout(r, 60))
    expect(f.calls()).toBe(0)
  })
})
