import { describe, expect, it } from 'vitest'
import { isAutoCard } from './autopilot'

describe('isAutoCard', () => {
  it('auto-submits only the routine setup cards', () => {
    for (const t of ['csv_import', 'store_basics', 'payroll', 'roles', 'training_matrix', 'department_staffing', 'events'] as const)
      expect(isAutoCard(t)).toBe(true)
  })

  it('never auto-submits decisions (or cards that need the user to type)', () => {
    for (const t of ['confirm_tags', 'propose_rule', 'tradeoff', 'conflict_menu', 'coverage_grid', 'employee_availability'] as const)
      expect(isAutoCard(t)).toBe(false)
  })
})
