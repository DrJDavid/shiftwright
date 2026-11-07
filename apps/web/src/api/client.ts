import type { Schedule, StoreConfig, ValidationReport } from '../contracts'
import type {
  CardSubmission,
  ChatEvent,
  ChatRequest,
  CreateStoreRequest,
  Health,
  Readiness,
  SolveResponse,
} from './protocol'
import { readSSE } from './sse'

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function errorText(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && 'detail' in body) return String((body as { detail: unknown }).detail)
    return JSON.stringify(body)
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

export function createApi(fetchImpl: FetchLike) {
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetchImpl(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
    if (!res.ok) throw new ApiError(res.status, await errorText(res))
    return (await res.json()) as T
  }
  const post = <T>(path: string, body: unknown) => json<T>(path, { method: 'POST', body: JSON.stringify(body) })
  const s = (id: string) => `/stores/${encodeURIComponent(id)}`

  return {
    health: () => json<Health>('/health'),
    createStore: (req: CreateStoreRequest) => post<StoreConfig>('/stores', req),
    getConfig: (id: string) => json<StoreConfig>(`${s(id)}/config`),
    putConfig: (id: string, cfg: StoreConfig) =>
      json<StoreConfig>(`${s(id)}/config`, { method: 'PUT', body: JSON.stringify(cfg) }),
    readiness: (id: string) => json<Readiness>(`${s(id)}/readiness`),
    solve: (id: string, timeLimitS?: number) =>
      post<SolveResponse>(`${s(id)}/solve`, timeLimitS ? { time_limit_s: timeLimitS } : {}),
    latestSchedule: (id: string) => json<{ schedule: Schedule; validation: ValidationReport }>(`${s(id)}/schedule`),
    submitCard: (id: string, sub: CardSubmission) => post<unknown>(`${s(id)}/chat/card`, sub),

    /** Streams one chat turn. Resolves when the stream closes. */
    async chat(id: string, req: ChatRequest, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
      const res = await fetchImpl(`/api${s(id)}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(req),
        signal,
      })
      if (!res.ok || !res.body) throw new ApiError(res.status, await errorText(res))
      await readSSE(res.body, (raw) => onEvent(raw as ChatEvent))
    },
  }
}

export type Api = ReturnType<typeof createApi>
