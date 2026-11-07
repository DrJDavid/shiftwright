import type { ComponentType } from 'react'
import type { CardType } from '../api/protocol'
import { CardFrame, type CardProps } from './CardFrame'
import { CoverageGridCard } from './CoverageGridCard'
import { CsvImportCard } from './CsvImportCard'
import { DepartmentStaffingCard } from './DepartmentStaffingCard'
import { EmployeeAvailabilityCard } from './EmployeeAvailabilityCard'
import { EventsCard } from './EventsCard'
import { ConflictMenuCard, TradeoffCard } from './OptionCards'
import { PayrollCard } from './PayrollCard'
import { ProposeRuleCard } from './ProposeRuleCard'
import { RolesCard } from './RolesCard'
import { StoreBasicsCard } from './StoreBasicsCard'
import { TrainingMatrixCard } from './TrainingMatrixCard'

// One component per card_type (API.md card catalogue). Props arrive untyped over the wire;
// each component narrows them to its API.md shape.
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- registry is heterogeneous by design
const REGISTRY: Partial<Record<CardType, ComponentType<CardProps<any, any> & { initialFile?: File }>>> = {
  store_basics: StoreBasicsCard,
  payroll: PayrollCard,
  roles: RolesCard,
  training_matrix: TrainingMatrixCard,
  coverage_grid: CoverageGridCard,
  department_staffing: DepartmentStaffingCard,
  events: EventsCard,
  csv_import: CsvImportCard,
  propose_rule: ProposeRuleCard,
  tradeoff: TradeoffCard,
  conflict_menu: ConflictMenuCard,
  employee_availability: EmployeeAvailabilityCard,
}

export function ChatCard(p: CardProps<unknown, unknown> & { cardType: CardType; cardId: string; initialFile?: File }) {
  const C = REGISTRY[p.cardType]
  if (C) return <C {...p} />
  return (
    <CardFrame
      title={p.cardType.replace(/_/g, ' ')}
      status={p.status}
      onCancel={p.onCancel}
      submitLabel="Continue"
      canSubmit={false}
      formId={`unsupported-${p.cardId}`}
    >
      <p className="text-sm text-ink-2">This step isn't available in the web app yet. Skip it to let the conversation continue.</p>
    </CardFrame>
  )
}
