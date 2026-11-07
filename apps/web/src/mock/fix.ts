// MOCK-ONLY call-out fixer and outreach loop, so the Fix tab works before WS1's fix_day lands.
// Not the engine: candidates are picked by a simple rule and every number is computed from the
// mock schedule (mockScore). Replies are scripted like WS6's demo messenger: rank 1 declines,
// rank 2 asks a question and then accepts, ~4 s apart. Manual replies (POST /sms/mock-reply) win.
import type {
  CallOut,
  Employee,
  FixAction,
  FixPlan,
  InboundMessage,
  OutboundMessage,
  OutreachCandidate,
  Schedule,
  Shift,
  StoreConfig,
} from '../contracts'
import type { FixRequestBody, OutreachState } from '../api/protocol'
import { fmtRange, WEEKDAY_NAMES } from '../lib/format'
import { mockScore } from './solver'

const REPLY_DELAY_MS = 4000

type Slot = { lost: Shift; queue: OutreachCandidate[] }
type SavedPlan = { plan: FixPlan; slots: Slot[]; base: Schedule; callouts: CallOut[] }

function hours(s: Shift) {
  return (s.end - s.start) / 60
}

export function mockFix(cfg: StoreConfig, schedule: Schedule, req: FixRequestBody, planId: string): SavedPlan {
  const slot = cfg.store.slot_minutes ?? 30
  const out = new Set(req.callouts.map((c) => c.employee_id))
  const lostShifts = (schedule.shifts ?? []).filter((s) => s.day === req.day && out.has(s.employee_id))
  const kept = (schedule.shifts ?? []).filter((s) => !(s.day === req.day && out.has(s.employee_id)))
  const weekHours = new Map<string, number>()
  for (const s of kept) weekHours.set(s.employee_id, (weekHours.get(s.employee_id) ?? 0) + hours(s))
  const working = new Set(kept.filter((s) => s.day === req.day).map((s) => s.employee_id))
  const roleName = new Map(cfg.roles.map((r) => [r.id, r.name]))
  const earliest = Math.ceil((req.now + 60) / slot) * slot // nobody can be in sooner than an hour from now
  const used = new Set<string>()
  let rank = 0

  const odds = (e: Employee) => {
    const a = e.attendance
    return a?.callins_offered_90d ? (a.callins_accepted_90d ?? 0) / a.callins_offered_90d : 0.5
  }

  const slots: Slot[] = lostShifts.map((lost) => {
    const role = lost.segments[0]?.role_id ?? ''
    const start = Math.max(lost.start, earliest)
    const proposedBase: Pick<Shift, 'day' | 'start' | 'end' | 'breaks' | 'segments'> = {
      day: lost.day,
      start,
      end: lost.end,
      breaks: (lost.breaks ?? []).filter((b) => b.start >= start),
      segments: lost.segments.filter((g) => g.end > start).map((g) => ({ ...g, start: Math.max(g.start, start) })),
    }
    const cands = cfg.employees
      .filter((e) => !out.has(e.id) && !working.has(e.id) && !used.has(e.id))
      .filter((e) => e.trained_role_ids.includes(role))
      .filter((e) => (weekHours.get(e.id) ?? 0) + (proposedBase.end - proposedBase.start) / 60 <= (e.max_hours_week ?? 40))
      .sort((a, b) => odds(b) - odds(a) || a.wage_per_hour - b.wage_per_hour)
      .slice(0, 3)
    cands.forEach((e) => used.add(e.id))
    const queue = cands.map((e): OutreachCandidate => {
      const shift: Shift = { ...proposedBase, id: `fix-${e.id}-${lost.day}`, employee_id: e.id }
      const a = e.attendance
      return {
        rank: ++rank,
        employee_id: e.id,
        proposed_shift: shift,
        added_cost_dollars: Math.round(hours(shift) * e.wage_per_hour * 100) / 100,
        est_accept_prob: Math.round(odds(e) * 100) / 100,
        why: [
          `Trained for ${roleName.get(role) ?? role}`,
          `off ${WEEKDAY_NAMES[lost.day]}`,
          `${weekHours.get(e.id) ?? 0}h of ${e.max_hours_week ?? 40}h this week`,
          a?.callins_offered_90d ? `took ${a.callins_accepted_90d ?? 0} of ${a.callins_offered_90d} extra shifts` : 'never asked before',
        ].join(', '),
      }
    })
    return { lost, queue }
  })

  const actions: FixAction[] = slots.map(({ lost, queue }) => {
    const role = lost.segments[0]?.role_id ?? null
    const who = cfg.employees.find((e) => e.id === lost.employee_id)?.name ?? lost.employee_id
    if (queue.length === 0)
      return {
        lever: 'drop_coverage',
        employee_id: null,
        role_id: role,
        start: lost.start,
        end: lost.end,
        added_cost_dollars: 0,
        rationale: `Nobody trained and free can cover ${who}'s ${fmtRange(lost.start, lost.end)}; leave it as a gap.`,
      }
    return {
      lever: 'call_in',
      employee_id: queue[0].employee_id,
      role_id: role,
      start: queue[0].proposed_shift.start,
      end: queue[0].proposed_shift.end,
      added_cost_dollars: queue[0].added_cost_dollars,
      rationale: `Cover ${who}'s ${roleName.get(role ?? '') ?? role} shift; text ${queue.length} people in order until one says yes.`,
    }
  })

  const none = mockScore(cfg, kept, 'mock-fix')
  const all = mockScore(cfg, [...kept, ...slots.flatMap((s) => (s.queue[0] ? [s.queue[0].proposed_shift] : []))], 'mock-fix')
  const plan: FixPlan = {
    plan_id: planId,
    actions,
    outreach_queue: slots.flatMap((s) => s.queue),
    schedule_if_all_accept: all,
    schedule_if_none_accept: none,
    coverage_before_pct: none.metrics?.coverage_pct ?? 0,
    coverage_after_best_pct: all.metrics?.coverage_pct ?? 0,
    coverage_after_worst_pct: none.metrics?.coverage_pct ?? 0,
  }
  return { plan, slots, base: { ...none, metrics: none.metrics }, callouts: req.callouts }
}

/** One outreach run: texts each slot's queue in order; scripted replies unless the leader replies first. */
export class MockOutreach {
  state: OutreachState = { plan_id: '', status: 'idle', current_rank: null, messages: [], accepted_employee_ids: [], schedule: null }
  private listeners = new Set<() => void>()
  private timers: ReturnType<typeof setTimeout>[] = []
  private waiting: { cand: OutreachCandidate; slotIdx: number; posInSlot: number; asked: boolean } | null = null
  private saved: SavedPlan | null = null
  private cfg: StoreConfig | null = null
  private shifts: Shift[] = []
  private seq = 0

  subscribe(fn: () => void) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private emit() {
    this.state = { ...this.state, messages: [...this.state.messages] }
    this.listeners.forEach((f) => f())
  }

  start(cfg: StoreConfig, saved: SavedPlan) {
    this.stop()
    this.cfg = cfg
    this.saved = saved
    this.shifts = [...(saved.base.shifts ?? [])]
    this.state = { plan_id: saved.plan.plan_id ?? '', status: 'texting', current_rank: null, messages: [], accepted_employee_ids: [], schedule: saved.base }
    this.next(0, 0)
  }

  stop() {
    this.timers.forEach(clearTimeout)
    this.timers = []
    this.waiting = null
    if (this.state.status === 'texting') {
      this.state.status = 'exhausted'
      this.state.current_rank = null
      this.emit()
    }
  }

  private emp(id: string) {
    return this.cfg?.employees.find((e) => e.id === id)
  }

  private next(slotIdx: number, posInSlot: number): void {
    const slots = this.saved?.slots ?? []
    if (slotIdx >= slots.length) {
      this.state.status = this.state.accepted_employee_ids.length >= slots.filter((s) => s.queue.length).length ? 'filled' : 'exhausted'
      this.state.current_rank = null
      this.emit()
      return
    }
    const cand = slots[slotIdx].queue[posInSlot]
    if (!cand) return this.next(slotIdx + 1, 0)
    const e = this.emp(cand.employee_id)
    const sh = cand.proposed_shift
    const roles = [...new Set(sh.segments.map((g) => this.cfg?.roles.find((r) => r.id === g.role_id)?.name ?? g.role_id))].join(', ')
    const msg: OutboundMessage = {
      id: `out_${++this.seq}`,
      to_employee_id: cand.employee_id,
      to_phone: e?.phone ?? '',
      body: `Hi ${e?.name.split(' ')[0] ?? ''}, ${this.cfg?.store.name} needs ${roles} ${WEEKDAY_NAMES[sh.day]} ${fmtRange(sh.start, sh.end)} at $${e?.wage_per_hour.toFixed(2)}/hr. Can you work it? Reply YES or NO`,
      sent_at: new Date().toISOString(),
      outreach_rank: cand.rank,
    }
    this.state.messages.push(msg)
    this.state.current_rank = cand.rank
    this.waiting = { cand, slotIdx, posInSlot, asked: false }
    this.emit()
    this.script()
  }

  /** Scripted replies: the first person texted declines; the next asks a question, then accepts. */
  private script() {
    const w = this.waiting
    if (!w) return
    const firstEver = this.state.messages.filter((m) => 'to_employee_id' in m).length === 1
    const phone = this.emp(w.cand.employee_id)?.phone ?? ''
    if (firstEver) this.timers.push(setTimeout(() => this.reply(phone, "Sorry, can't today"), REPLY_DELAY_MS))
    else if (!w.asked) this.timers.push(setTimeout(() => this.reply(phone, 'What time would I be done?'), REPLY_DELAY_MS))
    else this.timers.push(setTimeout(() => this.reply(phone, 'Ok yes I can come in'), REPLY_DELAY_MS))
  }

  /** Same path as POST /sms/mock-reply. Returns how the reply was read, or null if nobody is waiting on that phone. */
  reply(fromPhone: string, body: string): InboundMessage['interpreted_as'] {
    const w = this.waiting
    const digits = (p: string) => p.replace(/\D/g, '').slice(-10)
    if (!w || !this.cfg || digits(this.emp(w.cand.employee_id)?.phone ?? '') !== digits(fromPhone)) return null
    this.timers.forEach(clearTimeout)
    this.timers = []
    const t = body.trim().toLowerCase()
    const kind: InboundMessage['interpreted_as'] = /\?/.test(t)
      ? 'question'
      : /^(y|yes|yeah|yep|sure|ok|okay)\b/.test(t)
        ? 'accept'
        : /^(n|no|nope|nah|sorry|can't|cant)\b/.test(t)
          ? 'decline'
          : 'unknown'
    this.state.messages.push({ id: `in_${++this.seq}`, from_phone: fromPhone, body, received_at: new Date().toISOString(), interpreted_as: kind })
    if (kind === 'accept') {
      this.waiting = null
      this.state.accepted_employee_ids.push(w.cand.employee_id)
      this.shifts.push(w.cand.proposed_shift)
      this.state.schedule = mockScore(this.cfg, this.shifts, 'mock-fix')
      this.emit()
      this.timers.push(setTimeout(() => this.next(w.slotIdx + 1, 0), 600))
    } else if (kind === 'decline') {
      this.waiting = null
      this.emit()
      this.timers.push(setTimeout(() => this.next(w.slotIdx, w.posInSlot + 1), 600))
    } else {
      w.asked = true
      this.emit()
      this.script()
    }
    return kind
  }
}
