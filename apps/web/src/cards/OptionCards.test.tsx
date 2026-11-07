import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ConflictMenuCard } from './OptionCards'
import { CardEnvContext, type CardEnv } from './context'

const props = {
  infeasibility: { summary: 'Not enough people.', conflicting_law_rule_ids: ['US.minor_hours'], conflicting_constraint_ids: ['c_days'] },
  options: [],
} as never

const render = (env: CardEnv | null) =>
  renderToStaticMarkup(
    <CardEnvContext.Provider value={env}>
      <ConflictMenuCard props={props} status="open" onSubmit={() => {}} onCancel={() => {}} />
    </CardEnvContext.Provider>,
  )

describe('ConflictMenuCard', () => {
  it('lists involved rules by name, not id', () => {
    const names = { 'US.minor_hours': 'Under-16s work limited hours.', c_days: 'At most 5 days a week.' } as Record<string, string>
    const html = render({ ruleNames: { name: (id: string) => names[id], plain: (t: string) => t } } as never)
    expect(html).toContain('Under-16s work limited hours.')
    expect(html).toContain('At most 5 days a week.')
    expect(html).not.toContain('US.minor_hours')
  })

  it('falls back to spaced ids without rule names', () => {
    expect(render(null)).toContain('c days')
  })
})
