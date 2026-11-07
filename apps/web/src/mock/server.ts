// MOCK-ONLY in-browser implementation of the parts of contracts/API.md the web needs, including
// the SSE chat protocol (turn pauses on a card; POST /chat/card resumes the same stream).
// It returns real Response objects so the production client + SSE parser are exercised unchanged.
import type { Budget, Schedule, Store, StoreConfig, ValidationReport } from '../contracts'
import type { CardSubmission, ChatEvent, ChatRequest, CreateStoreRequest, Readiness } from '../api/protocol'
import type { FetchLike } from '../api/client'
import { mockStoreConfig } from './fixture'
import { mockSolve } from './solver'

type StoreState = {
  config: StoreConfig
  latest: { schedule: Schedule; validation: ValidationReport } | null
  basicsDone: boolean
  payrollDone: boolean
}

export function createMockFetch(opts: { latencyMs?: number } = {}): FetchLike {
  const latency = opts.latencyMs ?? 350
  const stores = new Map<string, StoreState>()
  const pendingCards = new Map<string, (result: unknown) => void>()
  let cardSeq = 0
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

  const ok = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const notFound = (detail: string) => ok({ detail }, 404)

  function bump(st: StoreState) {
    st.config = { ...st.config, config_version: (st.config.config_version ?? 1) + 1 }
  }

  function readiness(st: StoreState): Readiness {
    const c = st.config
    const checks = [
      { id: 'store_basics', label: 'Store basics', ok: st.basicsDone, detail: st.basicsDone ? c.store.name : 'Confirm name, location and hours' },
      { id: 'law_pack', label: 'Labor law for this location', ok: c.law_pack != null, detail: c.law_pack ? c.law_pack.coverage : 'Not resolved (mock API has no law data)' },
      { id: 'roles', label: 'Roles', ok: c.roles.length > 0, detail: `${c.roles.length} roles` },
      { id: 'employees', label: 'Employees', ok: c.employees.length > 0, detail: `${c.employees.length} people` },
      { id: 'budget', label: 'Payroll budget', ok: st.payrollDone, detail: st.payrollDone ? `${c.budget.weekly_hours_cap}h cap` : 'Set the weekly hours cap' },
    ]
    return { ready: checks.every((x) => x.ok), checks }
  }

  function chatStream(st: StoreState, req: ChatRequest, signal?: AbortSignal | null): Response {
    const enc = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      async start(ctrl) {
        const emit = (e: ChatEvent) => ctrl.enqueue(enc.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`))
        const say = async (text: string) => {
          for (const word of text.split(/(?<= )/)) {
            if (signal?.aborted) return
            emit({ event: 'text', data: { delta: word } })
            await sleep(latency ? 18 : 0)
          }
        }
        const card = <T,>(card_type: 'store_basics' | 'payroll', props: unknown) =>
          new Promise<T | { cancelled: true }>((resolve) => {
            const card_id = `card_${++cardSeq}`
            pendingCards.set(card_id, (r) => resolve(r as T | { cancelled: true }))
            emit({ event: 'card', data: { card_id, card_type, props } })
          })
        const isCancelled = (r: unknown): r is { cancelled: true } =>
          !!r && typeof r === 'object' && (r as { cancelled?: unknown }).cancelled === true

        try {
          const last = req.messages.at(-1)?.content ?? ''
          if (!st.basicsDone) {
            await say("Let's start with the store itself. Check these details and correct anything that's off.")
            const r = await card<Partial<Store>>('store_basics', st.config.store)
            if (isCancelled(r)) {
              await say('No problem. Tell me when you want to come back to store details.')
            } else {
              st.config = { ...st.config, store: { ...st.config.store, ...r, id: st.config.store.id } }
              st.basicsDone = true
              bump(st)
              emit({ event: 'config', data: { config_version: st.config.config_version ?? 1, patch_summary: ['Updated store basics'] } })
            }
          }
          if (st.basicsDone && !st.payrollDone) {
            await say('Next, the payroll budget corporate gave you for the week.')
            const r = await card<Budget>('payroll', st.config.budget)
            if (isCancelled(r)) {
              await say('Okay. The budget is still needed before I can build a schedule.')
            } else {
              st.config = { ...st.config, budget: { ...st.config.budget, ...r } }
              st.payrollDone = true
              bump(st)
              emit({ event: 'config', data: { config_version: st.config.config_version ?? 1, patch_summary: ['Set the weekly hours cap'] } })
            }
          }
          if (st.basicsDone && st.payrollDone) {
            if (/build|solve|schedule/i.test(last)) {
              emit({ event: 'tool', data: { name: 'solve', status: 'start', summary: 'Building the week' } })
              st.latest = mockSolve(st.config)
              emit({ event: 'tool', data: { name: 'solve', status: 'done', summary: 'Built the week' } })
              await say('Done. The schedule is in the Schedule tab.')
            } else {
              await say('Store basics and payroll are set. Use Build schedule to create the week. (The mock API only scripts these two steps.)')
            }
          }
          emit({ event: 'done', data: {} })
        } catch (err) {
          emit({ event: 'error', data: { message: String(err) } })
        } finally {
          ctrl.close()
        }
      },
    })
    return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }

  return async (input, init) => {
    const url = new URL(input, 'http://mock.local')
    const path = url.pathname.replace(/^\/api/, '')
    const method = (init?.method ?? 'GET').toUpperCase()
    const body: unknown = init?.body && typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    if (latency) await sleep(latency / 3)

    if (path === '/health') return ok({ ok: true, contract_version: '1.0.0', messenger: 'mock', model: 'mock' })
    if (path === '/stores' && method === 'POST') {
      const req = body as CreateStoreRequest
      const id = `mock-${stores.size + 1}`
      const st: StoreState = {
        config: mockStoreConfig(id, req.name, req.jurisdiction.state, req.jurisdiction.city ?? null),
        latest: null,
        basicsDone: false,
        payrollDone: false,
      }
      stores.set(id, st)
      return ok(st.config)
    }
    const m = path.match(/^\/stores\/([^/]+)(\/.*)$/)
    if (!m) return notFound(`No mock route for ${method} ${path}`)
    const st = stores.get(decodeURIComponent(m[1]))
    if (!st) return notFound('Store not found')
    const rest = m[2]

    if (rest === '/config' && method === 'GET') return ok(st.config)
    if (rest === '/config' && method === 'PUT') {
      st.config = body as StoreConfig
      bump(st)
      return ok(st.config)
    }
    if (rest === '/readiness') return ok(readiness(st))
    if (rest === '/solve' && method === 'POST') {
      if (latency) await sleep(latency * 3)
      st.latest = mockSolve(st.config)
      return ok(st.latest)
    }
    if (rest === '/schedule') return st.latest ? ok(st.latest) : notFound('No schedule yet')
    if (rest === '/chat' && method === 'POST') return chatStream(st, body as ChatRequest, init?.signal)
    if (rest === '/chat/card' && method === 'POST') {
      const sub = body as CardSubmission
      const resume = pendingCards.get(sub.card_id)
      if (!resume) return notFound('Unknown or already submitted card')
      pendingCards.delete(sub.card_id)
      resume(sub.result)
      return ok({ ok: true })
    }
    return notFound(`No mock route for ${method} ${path}`)
  }
}
