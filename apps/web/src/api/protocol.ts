// Shapes defined in contracts/API.md that are NOT in the generated contracts.ts
// (helper shapes and the chat/SSE protocol). Everything else comes from ./../contracts.
import type {
  AvailabilityEntry,
  CallOut,
  Budget,
  Constraint,
  DayHours,
  Department,
  Event,
  Infeasibility,
  Role,
  InboundMessage,
  Jurisdiction,
  OutboundMessage,
  Schedule,
  Sector,
  Store,
  ValidationReport,
} from '../contracts'

export type CardType =
  | 'store_basics'
  | 'payroll'
  | 'roles'
  | 'training_matrix'
  | 'coverage_grid'
  | 'department_staffing'
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

export type RolesProps = { departments: Department[]; roles: Role[] }
export type RolesResult = RolesProps
export type TrainingMatrixProps = { employees: { id: string; name: string; trained_role_ids?: string[] }[]; roles: Role[] }
export type TrainingMatrixResult = Record<string, string[]>
export type DayType = 'weekday' | 'saturday' | 'sunday' | 'truck_day' | 'custom'
export type CoverageGridProps = {
  day_type: DayType
  roles: Role[]
  slot_minutes: number
  days: number[]
  start_minute: number
  prefill: Record<string, number[]>
  /** Sent as a read-only preview (e.g. after department_staffing): render without inputs. */
  readonly?: boolean
}
/** API.md: "same grid". apps/api reads `prefill` (or `grid`) from the result. */
export type CoverageGridResult = { prefill: Record<string, number[]> }
export type DayGroupId = 'weekday' | 'saturday' | 'sunday'
/** API.md v1.3 department_staffing. Times are minutes after midnight. */
export type RoleStaffing = {
  base: number
  peaks: { day_group: DayGroupId | string; start: number; end: number; headcount: number }[]
  open: { headcount: number; minutes_before_open: number } | null
  close: { headcount: number; minutes_after_close: number } | null
}
export type DepartmentStaffingProps = {
  department: Department
  roles: Role[]
  day_groups: { id: DayGroupId | string; days: number[] }[]
  hours: DayHours[]
  pre_open_minutes: number
  post_close_minutes: number
  suggested: Record<string, RoleStaffing>
  /** v1.5: one plain sentence per role on what the suggestion is based on. */
  rationale?: Record<string, string>
}
export type DepartmentStaffingResult = { staffing: Record<string, RoleStaffing> }
export type EventsProps = { events: Event[] }
export type EventsResult = EventsProps
export type CsvImportKind = 'roster' | 'training' | 'availability' | 'forecast' | 'history'
export type CsvImportProps = { kind: CsvImportKind; preview?: ImportPreview }
export type CsvImportResult = { committed: boolean; rows: number }
export type ProposeRuleProps = { constraint: Constraint; evidence: string; plain_text: string }
export type ProposeRuleResult = { decision: 'hard' | 'soft' | 'not_a_rule'; weight_dollars?: number }
export type TradeoffOption = { id: string; label: string; cost_dollars: number; effect: string }
export type TradeoffProps = { question: string; options: TradeoffOption[] }
export type OptionResult = { option_id: string }
export type ConflictOption = { id: string; label: string; cost_dollars: number; patch_summary: string }
export type ConflictMenuProps = { infeasibility: Partial<Infeasibility>; options: ConflictOption[] }
export type EmployeeAvailabilityProps = { employee: { id: string; name: string }; parsed: AvailabilityEntry[]; original_text: string }
export type EmployeeAvailabilityResult = { confirmed: AvailabilityEntry[] }

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

/** v1.2: `demo` / `tiny` (and per-locality `demo_<city>` as WS6 adds them) load WS4 fixtures; name/jurisdiction optional then. */
export type CreateStoreRequest = {
  template?: 'bigbox_small' | 'bigbox_mid' | 'empty' | 'demo' | 'tiny' | `demo_${string}`
  name?: string
  jurisdiction?: Jurisdiction
  // PUNCHLIST A2: saved on create with template `empty`, so the chat doesn't re-ask.
  sector?: Sector
  business_description?: string
}

// PUNCHLIST A1 (accounts). Session is the `sw_session` cookie.
export type User = { id: string; email: string; name: string }
export type SignupRequest = { email: string; password: string; name: string }
export type LoginRequest = { email: string; password: string }
export type WorkplaceSummary = {
  id: string
  name: string
  sector: Sector | null
  city: string | null
  state: string | null
  updated_at: string
  has_schedule: boolean
}

/** `validation` is null when GET /schedule has a stored schedule that was never validated. */
export type SolveResponse = { schedule: Schedule; validation: ValidationReport | null }

export type Readiness = {
  ready: boolean
  /** v1.5 `severity`: warnings keep `ok: true`. */
  checks: { id: string; label: string; ok: boolean; detail: string; severity?: 'ok' | 'warn' | 'block' }[]
}

export type ImportPreview = {
  kind: string
  columns: string[]
  proposed_mapping: Record<string, string | null>
  unmapped_required: string[]
  rows_preview: object[]
  row_count: number
  warnings: string[]
  /** v1.2: fields a column may map to (in order) / must map. Older servers omit them. */
  target_fields?: string[]
  required_fields?: string[]
  /** v1.4: a need is met when all fields of any one alternative are mapped. */
  required_any_of?: { need: string; any_of: string[][] }[]
}

export type TemplateInfo = { id: string; label: string; jurisdiction: Jurisdiction | null }

export type PremiumByEmployee = { employee_id: string; premium_pay_dollars: number; law_rule_ids: string[]; note: string }
export type OutreachPremium = {
  status: 'not_applicable' | 'exempt' | 'owed'
  law_rule_ids: string[]
  note: string
  by_employee?: PremiumByEmployee[]
}

export type OutreachState = {
  plan_id: string
  status: 'idle' | 'texting' | 'filled' | 'exhausted'
  current_rank: number | null
  messages: (OutboundMessage | InboundMessage)[]
  accepted_employee_ids: string[]
  /** null before any outreach has run for the store. */
  schedule: Schedule | null
  /** v1.4 */
  mode?: 'one_to_one' | 'group_offer'
  wave?: number
  waiting_employee_ids?: string[]
  premium?: OutreachPremium | null
}

export type FixRequestBody = { callouts: CallOut[]; day: number; now: number }

export type Health = { ok: boolean; contract_version: string; messenger: string; model: string }
