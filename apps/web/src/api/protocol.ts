// Shapes defined in contracts/API.md that are NOT in the generated contracts.ts
// (helper shapes and the chat/SSE protocol). Everything else comes from ./../contracts.
import type {
  Budget,
  InboundMessage,
  Jurisdiction,
  OutboundMessage,
  Schedule,
  Store,
  ValidationReport,
} from '../contracts'

export type CardType =
  | 'store_basics'
  | 'payroll'
  | 'roles'
  | 'training_matrix'
  | 'coverage_grid'
  | 'events'
  | 'csv_import'
  | 'propose_rule'
  | 'tradeoff'
  | 'conflict_menu'
  | 'employee_availability'

/** Props/result pairs for the cards implemented so far (API.md card catalogue). */
export type StoreBasicsProps = Partial<Store>
export type StoreBasicsResult = Partial<Store>
export type PayrollProps = Partial<Budget>
export type PayrollResult = Budget

export type CardEnvelope = { card_id: string; card_type: CardType; props: unknown }

export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  card?: CardEnvelope & { result: unknown }
}

export type ChatMode = 'onboard' | 'review' | 'fix'
export type ChatRequest = { mode: ChatMode; messages: ChatMessage[] }
export type CardSubmission = { card_id: string; result: unknown }

export type ChatEvent =
  | { event: 'text'; data: { delta: string } }
  | { event: 'card'; data: CardEnvelope }
  | { event: 'config'; data: { config_version: number; patch_summary: string[] } }
  | { event: 'tool'; data: { name: string; status: 'start' | 'done'; summary: string } }
  | { event: 'done'; data: Record<string, never> }
  | { event: 'error'; data: { message: string } }

export type CreateStoreRequest = {
  template?: 'bigbox_small' | 'bigbox_mid' | 'empty'
  name: string
  jurisdiction: Jurisdiction
}

/** `validation` is null when GET /schedule has a stored schedule that was never validated. */
export type SolveResponse = { schedule: Schedule; validation: ValidationReport | null }

export type Readiness = {
  ready: boolean
  checks: { id: string; label: string; ok: boolean; detail: string }[]
}

export type ImportPreview = {
  kind: string
  columns: string[]
  proposed_mapping: Record<string, string | null>
  unmapped_required: string[]
  rows_preview: object[]
  row_count: number
  warnings: string[]
}

export type OutreachState = {
  plan_id: string
  status: 'idle' | 'texting' | 'filled' | 'exhausted'
  current_rank: number | null
  messages: (OutboundMessage | InboundMessage)[]
  accepted_employee_ids: string[]
  schedule: Schedule
}

export type Health = { ok: boolean; contract_version: string; messenger: string; model: string }
