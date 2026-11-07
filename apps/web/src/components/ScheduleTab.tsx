import { useMemo } from 'react'
import type { Gap, LawRule, StoreConfig } from '../contracts'
import type { SolveResponse } from '../api/protocol'
import { roleColors } from '../lib/roles'
import { ScheduleGrid } from './ScheduleGrid'
import { ScheduleStats } from './ScheduleStats'
import { SolveButton, type SolveState } from './SolveButton'
import { SolveProgress } from './SolveProgress'

type Props = {
  config: StoreConfig
  result: SolveResponse | null
  solve: SolveState
  onSolve: () => void
  onGapClick?: (g: Gap) => void
  onDayClick?: (day: number) => void
  callouts?: { employee_id: string; day: number }[]
  lawRules?: LawRule[]
}

export function ScheduleTab({ config, result, solve, onSolve, onGapClick, onDayClick, callouts, lawRules }: Props) {
  const colors = useMemo(() => roleColors(config.roles), [config.roles])
  const names = useMemo(() => new Map(config.employees.map((e) => [e.id, e.name])), [config.employees])

  if (!result) {
    return (
      <div className="relative flex flex-1 items-center justify-center p-10">
        {solve.status === 'running' && <SolveProgress startedAt={solve.startedAt} />}
        <div className="max-w-md">
          <h2 className="text-xl font-semibold">No schedule for this week yet</h2>
          <p className="mt-2 text-ink-2">
            Confirm the store details and payroll budget in the chat, then build the week. The solver creates every
            shift; the validator checks it before you see it.
          </p>
          <div className="mt-5">
            <SolveButton state={solve} onSolve={onSolve} />
          </div>
        </div>
      </div>
    )
  }

  const { schedule, validation } = result
  const stale = (schedule.config_version ?? 0) < (config.config_version ?? 0)

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {solve.status === 'running' && <SolveProgress startedAt={solve.startedAt} />}
      <ScheduleStats schedule={schedule} validation={validation} employeeName={(id) => names.get(id) ?? id} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule bg-panel px-4 py-2 text-xs text-ink-2">
        {config.roles.map((r) => (
          <span key={r.id} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: colors.get(r.id) }} />
            {r.name}
            {r.tipped && <span className="text-warn">(tipped)</span>}
          </span>
        ))}
        <span className="flex items-center gap-1.5 text-muted">
          <span className="inline-block h-2.5 w-4 rounded-sm border border-dashed border-muted" />
          Gap in a bar is a break
        </span>
        <span className="ml-auto flex items-center gap-3">
          {stale && <span className="font-medium text-warn">Settings changed since this was built</span>}
          <SolveButton state={solve} onSolve={onSolve} compact label="Rebuild" />
        </span>
      </div>
      {schedule.status === 'infeasible' && schedule.infeasibility && (
        <div className="border-b border-gap/30 bg-gap-wash px-4 py-2 text-sm text-gap">
          No legal schedule exists with the current hard rules. {schedule.infeasibility.summary}
        </div>
      )}
      <ScheduleGrid schedule={schedule} config={config} onGapClick={onGapClick} onDayClick={onDayClick} callouts={callouts} lawRules={lawRules} />
    </div>
  )
}
