import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ScheduleGrid } from './ScheduleGrid'
import { mockStoreConfig } from '../mock/fixture'
import type { Schedule } from '../contracts'

describe('ScheduleGrid', () => {
  it('draws split shifts as two bars on one day (v1.5)', () => {
    const cfg = mockStoreConfig('t', 'bigbox_small', 'S', 'TX', null)
    const e = cfg.employees[0]
    const role = e.trained_role_ids[0]
    const schedule: Schedule = {
      store_id: 't',
      week_start: cfg.store.week_start,
      produced_by: 'test',
      config_version: 1,
      status: 'feasible',
      shifts: [
        { id: 'a', employee_id: e.id, day: 2, start: 660, end: 840, segments: [{ role_id: role, start: 660, end: 840 }] },
        { id: 'b', employee_id: e.id, day: 2, start: 1020, end: 1260, segments: [{ role_id: role, start: 1020, end: 1260 }] },
      ],
    }
    const html = renderToStaticMarkup(<ScheduleGrid schedule={schedule} config={cfg} />)
    expect(html.replace(/<[^>]+>/g, '')).toContain('11a–2p, 5p–9p')
    expect(html.match(/cursor-pointer/g)?.length).toBeGreaterThanOrEqual(2)
  })
})
