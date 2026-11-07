// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createApi, type FetchLike } from '../api/client'
import type { Kickoff } from '../api/protocol'
import { createMockFetch } from '../mock/server'
import { ChatPane } from './ChatPane'

beforeAll(() => {
  Element.prototype.scrollTo ??= () => {}
})
afterEach(cleanup)

type Call = { url: string; method: string; body: unknown }

async function generatedStore() {
  const mock = createMockFetch({ latencyMs: 0 })
  const calls: Call[] = []
  const spy: FetchLike = (url, init) => {
    calls.push({ url, method: init?.method ?? 'GET', body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined })
    return mock(url, init)
  }
  const api = createApi(spy)
  await api.signup({ email: 'm@x.com', password: 'longenough', name: 'M' })
  const g = await api.generatedWorkplace({ sector: 'food' })
  return { api, calls, storeId: g.store_id, kickoff: g.kickoff }
}

function pane(api: ReturnType<typeof createApi>, storeId: string, kickoff: Kickoff, opts: { autopilot: boolean; delayMs: number }) {
  return render(
    <ChatPane
      api={api}
      storeId={storeId}
      mode="onboard"
      onConfigChanged={() => {}}
      onScheduleChanged={() => {}}
      kickoff={kickoff}
      autopilotDefault={opts.autopilot}
      autopilotDelayMs={opts.delayMs}
    />,
  )
}

const cardPosts = (calls: Call[]) => calls.filter((c) => c.url.endsWith('/chat/card')).map((c) => c.body as { card_id: string; result: unknown })

describe('B7 kickoff', () => {
  it('sends the manager message once, with file chips and the attachments on the request', async () => {
    const { api, calls, storeId, kickoff } = await generatedStore()
    pane(api, storeId, kickoff, { autopilot: false, delayMs: 50 })
    await screen.findByText(kickoff.message)
    const chips = screen.getByRole('list', { name: 'Attached files' })
    expect(within(chips).getAllByRole('listitem').map((li) => li.textContent)).toEqual(
      kickoff.attachments.map((a) => `${a.filename} · ${a.row_count} rows`),
    )
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/chat'))).toHaveLength(1))
    const req = calls.find((c) => c.url.endsWith('/chat'))!.body as { messages: { content: string; attachments: unknown }[] }
    expect(req.messages).toEqual([{ role: 'user', content: kickoff.message, attachments: [{ kind: 'roster' }, { kind: 'training' }, { kind: 'forecast' }] }])
    // Autopilot off (a real workplace's default): the first card waits for the user.
    await screen.findByText('Import roster CSV')
    await new Promise((r) => setTimeout(r, 120))
    expect(cardPosts(calls)).toEqual([])
    expect(screen.getByRole('button', { name: 'Autopilot off · Turn on' })).toBeTruthy()
  })
})

describe('B7 autopilot', () => {
  it('submits routine cards as prefilled, then stops at the decision card', async () => {
    const { api, calls, storeId, kickoff } = await generatedStore()
    pane(api, storeId, kickoff, { autopilot: true, delayMs: 30 })
    expect(screen.getByRole('button', { name: 'Autopilot on · Pause' })).toBeTruthy()
    // The three attached imports go through on their own, answered with the cached preview's mapping.
    await screen.findByText('Check the equipment tags', {}, { timeout: 3000 })
    const posts = cardPosts(calls)
    expect(posts).toHaveLength(3)
    for (const p of posts) expect(p.result).toHaveProperty('mapping')

    // confirm_tags never auto-submits, however long it waits.
    await new Promise((r) => setTimeout(r, 200))
    expect(cardPosts(calls)).toHaveLength(3)
    expect(screen.queryByText(/Looks right, continuing/)).toBeNull()

    // The user decides; autopilot then carries on with the routine cards after it.
    fireEvent.click(screen.getByLabelText('Keep tags'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(cardPosts(calls).length).toBeGreaterThanOrEqual(5), { timeout: 3000 })
    expect(cardPosts(calls)[3].result).toEqual({ decisions: { pit_operator: 'keep' } })
  })

  it('hands the card back when the user clicks it', async () => {
    const { api, calls, storeId, kickoff } = await generatedStore()
    pane(api, storeId, kickoff, { autopilot: true, delayMs: 300 })
    await screen.findByText('Import roster CSV')
    expect(screen.getByRole('status').textContent).toMatch(/Looks right, continuing…/)
    fireEvent.pointerDown(screen.getAllByLabelText(/^Map /)[0])
    expect(screen.queryByText(/Looks right, continuing/)).toBeNull()
    await new Promise((r) => setTimeout(r, 450))
    expect(cardPosts(calls)).toEqual([])
    // Control is the user's: their own Import goes through.
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(cardPosts(calls)).toHaveLength(1))
  })

  it('Pause stops the countdown', async () => {
    const { api, calls, storeId, kickoff } = await generatedStore()
    pane(api, storeId, kickoff, { autopilot: true, delayMs: 300 })
    await screen.findByText('Import roster CSV')
    fireEvent.click(screen.getByRole('button', { name: 'Autopilot on · Pause' }))
    expect(screen.queryByText(/Looks right, continuing/)).toBeNull()
    await new Promise((r) => setTimeout(r, 450))
    expect(cardPosts(calls)).toEqual([])
  })
})
