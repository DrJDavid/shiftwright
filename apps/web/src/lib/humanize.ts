// Engine/API prose sometimes carries ids ("e004", "leader_on_duty") and 24-hour times ("12:30–22:00").
// For display only: swap known ids for names and times for 12-hour ("12:30p"). Unknown tokens stay as-is.
import type { StoreConfig } from '../contracts'
import { fmtTime } from './format'

export function humanizer(config: StoreConfig): (text: string) => string {
  const names = new Map<string, string>()
  for (const e of config.employees) names.set(e.id, e.name)
  for (const r of config.roles) names.set(r.id, r.name)
  const idRx = names.size ? new RegExp(`\\b(${[...names.keys()].map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, 'g') : null
  return (text: string) => {
    let t = text.replace(/\b([01]?\d|2[0-3]):([0-5]\d)\b/g, (_, h: string, m: string) => fmtTime(Number(h) * 60 + Number(m)))
    if (idRx) t = t.replace(idRx, (id) => names.get(id) ?? id)
    return t
  }
}
