import type { FixPlan, Gap, GapReason, Jurisdiction, LawPack, Schedule, StoreConfig, ValidationReport } from '../contracts'
import type {
  CardSubmission,
  ChatEvent,
  ChatRequest,
  CreateStoreRequest,
  CsvImportKind,
  FixRequestBody,
  OutreachState,
  TemplateInfo,
  Health,
  ImportPreview,
  LoginRequest,
  Readiness,
  SignupRequest,
  SolveResponse,
  User,
  WorkplaceSummary,
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
    if (body && typeof body === 'object' && 'detail' in body) {
      const d = (body as { detail: unknown }).detail
      return typeof d === 'string' ? d : JSON.stringify(d)
    }
    return JSON.stringify(body)
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

type ApiOptions = {
  demoKey?: string | null
  /** Called on any 401 outside login/signup: the session is gone, so the app should show the sign-in page. */
  onUnauthorized?: () => void
}

export function createApi(fetchImpl: FetchLike, opts: ApiOptions = {}) {
  const keyHeader: Record<string, string> = opts.demoKey ? { 'X-Demo-Key': opts.demoKey } : {}
  async function fail(res: Response, path: string): Promise<never> {
    if (res.status === 401 && !/^\/auth\/(login|signup)$/.test(path)) opts.onUnauthorized?.()
    throw new ApiError(res.status, await errorText(res))
  }
  async function send(path: string, init?: RequestInit): Promise<Response> {
    const res = await fetchImpl(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...keyHeader, ...(init?.headers ?? {}) },
    })
    return res.ok ? res : fail(res, path)
  }
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await (await send(path, init)).json()) as T
  }
  const post = <T>(path: string, body: unknown) => json<T>(path, { method: 'POST', body: JSON.stringify(body) })
  const s = (id: string) => `/stores/${encodeURIComponent(id)}`

  return {
    health: () => json<Health>('/health'),
    signup: (req: SignupRequest) => post<{ user: User }>('/auth/signup', req),
    login: (req: LoginRequest) => post<{ user: User }>('/auth/login', req),
    async logout(): Promise<void> {
      await send('/auth/logout', { method: 'POST' })
    },
    me: () => json<{ user: User }>('/auth/me'),
    workplaces: () => json<{ workplaces: WorkplaceSummary[] }>('/workplaces'),
    /** A copy of a demo store, owned by the caller, named "Sample: …" (listed with `sample_of` set). */
    sampleWorkplace: (template: string) => post<StoreConfig>('/workplaces/sample', { template }),
    createStore: (req: CreateStoreRequest) => post<StoreConfig>('/stores', req),
    getConfig: (id: string) => json<StoreConfig>(`${s(id)}/config`),
    putConfig: (id: string, cfg: StoreConfig) =>
      json<StoreConfig>(`${s(id)}/config`, { method: 'PUT', body: JSON.stringify(cfg) }),
    readiness: (id: string) => json<Readiness>(`${s(id)}/readiness`),
    solve: (id: string, timeLimitS?: number) =>
      post<SolveResponse>(`${s(id)}/solve`, timeLimitS ? { time_limit_s: timeLimitS } : {}),
    latestSchedule: (id: string) => json<SolveResponse>(`${s(id)}/schedule`),
    resolveLaw: (j: Jurisdiction) =>
      json<LawPack>(`/laws/resolve?state=${encodeURIComponent(j.state)}${j.city ? `&city=${encodeURIComponent(j.city)}` : ''}`),
    explainGap: (id: string, gap: Gap) => post<{ text: string; reasons: GapReason[] }>(`${s(id)}/gaps/explain`, { gap }),
    /** Multipart upload; the server parses and proposes a column mapping. Nothing is saved yet. */
    async importPreview(id: string, kind: CsvImportKind, file: File): Promise<ImportPreview> {
      const form = new FormData()
      form.append('file', file)
      const res = await fetchImpl(`/api${s(id)}/import/${kind}`, { method: 'POST', body: form, headers: keyHeader })
      if (!res.ok) return fail(res, `${s(id)}/import/${kind}`)
      return (await res.json()) as ImportPreview
    },
    /** Commits an import; v1.4 also returns the commit's warnings (header X-Import-Warning-Count, then GET). */
    async importCommit(id: string, kind: CsvImportKind, mapping: Record<string, string | null>, rows: object[]) {
      const res = await fetchImpl(`/api${s(id)}/import/${kind}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...keyHeader },
        body: JSON.stringify({ mapping, rows }),
      })
      if (!res.ok) return fail(res, `${s(id)}/import/${kind}/commit`)
      const config = (await res.json()) as StoreConfig
      let warnings: string[] = []
      if (Number(res.headers.get('X-Import-Warning-Count') ?? 0) > 0) {
        try {
          warnings = (await json<{ warnings: string[] }>(`${s(id)}/import/${kind}/warnings`)).warnings
        } catch {
          /* older server */
        }
      }
      return { config, warnings }
    },
    templates: () => json<{ templates: TemplateInfo[] }>('/templates'),
    equipmentRole: (id: string, roleId: string, decision: 'confirm' | 'reject') =>
      post<StoreConfig>(`${s(id)}/equipment_roles`, { role_id: roleId, decision }),
    validate: (id: string, schedule: Schedule) => post<ValidationReport>(`${s(id)}/validate`, schedule),
    fix: (id: string, body: FixRequestBody) => post<FixPlan>(`${s(id)}/fix`, body),
    /** v1.5: save the plan's immediate changes (call-outs removed, actions applied) without texting. */
    fixApply: (id: string, planId: string) => post<SolveResponse>(`${s(id)}/fix/apply`, { plan_id: planId }),
    outreachStart: (id: string, planId: string) => post<OutreachState>(`${s(id)}/outreach/start`, { plan_id: planId }),
    outreachCancel: (id: string) => post<OutreachState>(`${s(id)}/outreach/cancel`, {}),
    outreach: (id: string) => json<OutreachState>(`${s(id)}/outreach`),
    /** MESSENGER=mock only: reply as the employee. Same code path as a real inbound SMS. */
    mockReply: (fromPhone: string, body: string) =>
      post<{ ok: boolean; interpreted_as: string | null }>('/sms/mock-reply', { from_phone: fromPhone, body }),
    /** SSE `state` snapshots until the outreach stops texting. Resolves when the stream closes. */
    async outreachStream(id: string, onState: (st: OutreachState) => void, signal?: AbortSignal) {
      const res = await fetchImpl(`/api${s(id)}/outreach/stream`, { headers: { Accept: 'text/event-stream', ...keyHeader }, signal })
      if (!res.ok || !res.body) return fail(res, `${s(id)}/outreach/stream`)
      await readSSE(res.body, (e) => {
        if (e.event === 'state') onState(e.data as OutreachState)
      })
    },
    submitCard: (id: string, sub: CardSubmission) => post<unknown>(`${s(id)}/chat/card`, sub),

    /** Streams one chat turn. Resolves when the stream closes. */
    async chat(id: string, req: ChatRequest, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
      const res = await fetchImpl(`/api${s(id)}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...keyHeader },
        body: JSON.stringify(req),
        signal,
      })
      if (!res.ok || !res.body) return fail(res, `${s(id)}/chat`)
      await readSSE(res.body, (raw) => onEvent(raw as ChatEvent))
    },
  }
}

export type Api = ReturnType<typeof createApi>
