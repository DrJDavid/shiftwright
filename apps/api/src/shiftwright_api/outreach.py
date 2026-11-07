"""Outreach orchestrator: text call-in candidates one at a time for a FixPlan.

rank 1 -> wait (timeout) -> accept: commit their shift, recompute, re-run fix_day to see whether
more coverage is still needed -> decline/timeout: add to declined_employee_ids, re-run fix_day,
text the next. Stops when fix_day's queue is empty after an accept (filled) or no one is left (exhausted).
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shiftwright_contracts.models import (
    CallOut,
    FixPlan,
    FixRequest,
    InboundMessage,
    OutreachCandidate,
    Schedule,
    StoreConfig,
)

from . import integrations
from .db import Database
from .explain import DAYS, clock
from .messenger import Messenger, RecipientBlocked, interpret
from .models import OutreachState
from . import predictive


def offer_text(config: StoreConfig, cand: OutreachCandidate, extra: list[str] | None = None) -> str:
    """`extra`: sentences the law requires (mass-communication / voluntary statements), from predictive.py."""
    emp = next(e for e in config.employees if e.id == cand.employee_id)
    sh = cand.proposed_shift
    roles = {r.id: r.name for r in config.roles}
    role_names = ", ".join(dict.fromkeys(roles.get(s.role_id, s.role_id) for s in sh.segments)) or "a shift"
    first = emp.name.split(" ")[0]
    return (f"Hi {first}, {config.store.name} needs {role_names} {DAYS[sh.day]} {clock(sh.start)}-{clock(sh.end)} "
            f"at ${emp.wage_per_hour:.2f}/hr. {' '.join(extra or [])}{' ' if extra else ''}"
            "Can you work it? Reply YES or NO")


FILLED_TEXT = "Thanks! This shift has been filled, so no action is needed."


def answer_text(config: StoreConfig, cand: OutreachCandidate) -> str:
    """Reply to an employee's question: restate the offer's own facts (no new ones)."""
    emp = next(e for e in config.employees if e.id == cand.employee_id)
    sh = cand.proposed_shift
    roles = {r.id: r.name for r in config.roles}
    role_names = ", ".join(dict.fromkeys(roles.get(s.role_id, s.role_id) for s in sh.segments)) or "the shift"
    return (f"It's {role_names}, {DAYS[sh.day]} {clock(sh.start)} to {clock(sh.end)}, ${emp.wage_per_hour:.2f}/hr. "
            f"Your manager will see any other questions. Reply YES or NO")


AUTOREPLY_MODES = ("off", "script", "prob")
SCRIPT_DECLINE = "Sorry, can't today"
SCRIPT_QUESTION = "What time?"
SCRIPT_ACCEPT = "Yes I can"


@dataclass
class Run:
    store_id: str
    plan_id: str
    plan: FixPlan
    callouts: list[CallOut]
    day: int
    now: int
    schedule: Schedule
    state: OutreachState
    declined: list[str] = field(default_factory=list)
    replies: asyncio.Queue = field(default_factory=asyncio.Queue)
    waiting: dict = field(default_factory=dict)  # phone -> (employee, candidate) we're waiting to hear from
    task: Optional[asyncio.Task] = None
    auto_tasks: dict = field(default_factory=dict)  # phone -> simulated reply task (mock messenger)
    policy: Optional[predictive.Policy] = None
    posted: Optional[Schedule] = None  # the schedule fix_day planned against (re-fixes use it + booked shifts)
    booked: list = field(default_factory=list)  # call-in shifts accepted so far
    texted: int = 0  # how many people this run has texted (drives the scripted demo replies)


class OutreachBusy(RuntimeError):
    """An outreach is already texting for this store (limit: one active outreach per store)."""


TEXT_WINDOW_S = 3600.0


class OutreachManager:
    def __init__(self, db: Database, messenger: Messenger, llm, timeout_s: float, max_texts_per_hour: int = 20,
                 autoreply: str = "off", reply_delay_s: float = 4.0, seed: int = 417):
        self.db, self.messenger, self.llm, self.timeout_s = db, messenger, llm, timeout_s
        self.max_texts_per_hour = max_texts_per_hour
        # Simulated replies only ever apply to the mock messenger.
        self.autoreply = autoreply if messenger.name == "mock" and autoreply in AUTOREPLY_MODES else "off"
        self.reply_delay_s, self.seed = reply_delay_s, seed
        self.runs: dict[str, Run] = {}
        self.sent_at: dict[str, deque[float]] = {}  # store_id -> monotonic send times (last hour)
        self.changed: dict[str, asyncio.Event] = {}  # store_id -> set (then replaced) on every state change

    def change_event(self, store_id: str) -> asyncio.Event:
        """An event that is set the next time this store's outreach state changes."""
        return self.changed.setdefault(store_id, asyncio.Event())

    def _notify(self, store_id: str) -> None:
        ev = self.changed.pop(store_id, None)
        if ev:
            ev.set()

    def _texts_left(self, store_id: str) -> int:
        q = self.sent_at.setdefault(store_id, deque())
        now = time.monotonic()
        while q and now - q[0] > TEXT_WINDOW_S:
            q.popleft()
        return self.max_texts_per_hour - len(q)

    @staticmethod
    def _note(run: Run, text: str) -> None:
        run.state.messages.append(InboundMessage(
            id="sys_" + uuid.uuid4().hex[:8], from_phone="system", body=text,
            received_at=datetime.now(timezone.utc), interpreted_as="unknown"))

    # ---------------------------------------------------------------- plans
    def save_plan(self, store_id: str, plan: FixPlan, callouts: list[CallOut], day: int, now: int,
                  schedule: Schedule) -> FixPlan:
        plan_id = "plan_" + uuid.uuid4().hex[:10]
        plan = plan.model_copy(update={"plan_id": plan_id})
        self.db.put(store_id, "fix_plan", plan_id, {
            "plan": plan.model_dump(mode="json"), "callouts": [c.model_dump(mode="json") for c in callouts],
            "day": day, "now": now, "schedule": schedule.model_dump(mode="json")})
        return plan

    def apply_plan(self, store_id: str, plan_id: str) -> Schedule:
        """Save the plan's schedule_if_none_accept: the called-out employees' remaining shifts removed and the
        immediate actions (extend/reassign/drop) applied, with recomputed metrics and a fresh validation.
        Idempotent per plan."""
        saved = self.db.get(store_id, "fix_plan", plan_id)
        if not saved:
            raise KeyError(plan_id)
        if saved.get("applied"):
            return Schedule.model_validate(saved["applied"])
        plan = FixPlan.model_validate(saved["plan"])
        sched, report = validated(self.db.get_config(store_id), plan.schedule_if_none_accept)
        self.db.save_schedule(store_id, sched, report)
        saved["applied"] = sched.model_dump(mode="json")
        self.db.put(store_id, "fix_plan", plan_id, saved)
        return sched

    def state(self, store_id: str) -> OutreachState:
        run = self.runs.get(store_id)
        if run:
            return run.state
        saved = self.db.get(store_id, "outreach", "state")
        return OutreachState.model_validate(saved) if saved else OutreachState()

    def _persist(self, run: Run) -> None:
        self.db.put(run.store_id, "outreach", "state", run.state.model_dump(mode="json"))
        self._notify(run.store_id)

    # ---------------------------------------------------------------- start
    async def start(self, store_id: str, plan_id: str) -> OutreachState:
        saved = self.db.get(store_id, "fix_plan", plan_id)
        if not saved:
            raise KeyError(plan_id)
        old = self.runs.get(store_id)
        if old and old.task and not old.task.done():
            raise OutreachBusy("An outreach is already running for this store; cancel it first.")
        plan = FixPlan.model_validate(saved["plan"])
        schedule = await asyncio.to_thread(self.apply_plan, store_id, plan_id)
        run = Run(store_id=store_id, plan_id=plan_id, plan=plan,
                  callouts=[CallOut.model_validate(c) for c in saved["callouts"]], day=saved["day"],
                  now=saved["now"], schedule=schedule, posted=Schedule.model_validate(saved["schedule"]),
                  state=OutreachState(plan_id=plan_id, status="texting", schedule=schedule))
        mode = plan.outreach_mode or "one_to_one"  # SEMANTICS #17: send in the plan's mode
        try:
            cfg = self.db.get_config(store_id)
            run.policy = predictive.policy(cfg, integrations.resolve_law(cfg.store.jurisdiction), mode)
        except Exception as e:  # noqa: BLE001 - law lookup failed: plan's mode, premium unknown
            run.policy = predictive.Policy(mode=mode, min_recipients=2 if mode == "group_offer" else 1,
                                           premium_status="owed", note=f"Law pack unavailable ({e}); premium may be owed.")
        run.state.mode = run.policy.mode
        by_emp = premium_breakdown(plan)
        run.state.premium = {**run.policy.premium(), "by_employee": by_emp}
        if run.policy.premium_status == "owed" and by_emp and not any(b["premium_pay_dollars"] for b in by_emp):
            run.state.premium["note"] += " The plan prices it at $0.00 (the engine did not compute a premium)."
        self.runs[store_id] = run
        run.task = asyncio.create_task(self._run(run))
        await asyncio.sleep(0)  # let the first text go out
        return run.state

    async def cancel(self, store_id: str) -> OutreachState:
        run = self.runs.get(store_id)
        if run and run.task and not run.task.done():
            self._stop_auto(run)
            run.task.cancel()
            try:
                await run.task
            except asyncio.CancelledError:
                pass
            run.waiting = {}
            run.state.status, run.state.current_rank = "exhausted", None
            self._note(run, "Outreach cancelled by the leader.")
            self._persist(run)
        return self.state(store_id)

    # ---------------------------------------------------------------- inbound
    async def inbound(self, from_phone: str, body: str, manual: bool = False) -> Optional[InboundMessage]:
        """A reply arrived (Twilio webhook, mock-reply endpoint, or the simulated replier).
        `manual=True` (POST /api/sms/mock-reply) cancels any pending simulated reply for that person."""
        run = next((r for r in self.runs.values() if r.state.status == "texting" and _waiting_key(r, from_phone)),
                   None)
        if run is not None and manual:
            self._stop_auto(run, _waiting_key(run, from_phone))
        kind = await interpret(body, self.llm)
        msg = InboundMessage(id="in_" + uuid.uuid4().hex[:10], from_phone=from_phone, body=body,
                             received_at=datetime.now(timezone.utc), interpreted_as=kind)
        self.db.log_message(msg.id, run.store_id if run else None, "in", msg.model_dump(mode="json"))
        if run is None:
            return msg
        run.state.messages.append(msg)
        self._persist(run)
        await run.replies.put(msg)
        return msg

    # ---------------------------------------------------------------- loop
    async def _send(self, run: Run, emp, body: str, rank: Optional[int]) -> bool:
        try:
            out = await self.messenger.send(emp, body, outreach_rank=rank)
        except RecipientBlocked as e:
            self._note(run, str(e))
            return False
        self.sent_at.setdefault(run.store_id, deque()).append(time.monotonic())
        self.db.log_message(out.id, run.store_id, "out", out.model_dump(mode="json"))
        run.state.messages.append(out)
        return True

    async def _run(self, run: Run) -> None:
        """Waves of offers: 1 person at a time (one_to_one), or the top N at once (group_offer, when the law's
        exemption needs a mass communication). Each person is offered their own proposed shift. A YES fills
        only that shift; after it, the engine re-plans, and others in the wave whose offer is no longer needed
        hear it's filled while the rest keep waiting."""
        queue = list(run.plan.outreach_queue)
        pol = run.policy or predictive.Policy()
        try:
            while True:
                config = self.db.get_config(run.store_id)
                emps = {e.id: e for e in config.employees}
                cands = [c for c in sorted(queue, key=lambda c: c.rank)
                         if c.employee_id not in run.declined and c.employee_id not in run.state.accepted_employee_ids]
                for c in [c for c in cands if c.employee_id not in emps]:  # never text a guess
                    run.declined.append(c.employee_id)
                cands = [c for c in cands if c.employee_id in emps]
                if not cands:
                    run.state.status, run.state.current_rank = "exhausted", None
                    break
                wave = cands[:pol.min_recipients] if pol.mode == "group_offer" else cands[:1]
                if pol.mode == "group_offer" and len(wave) < pol.min_recipients:
                    note = (f"Only {len(wave)} candidate left for this offer: not a mass communication "
                            f"(needs {pol.min_recipients}+), so the premium is owed if they accept.")
                    run.state.premium = {**(run.state.premium or {}), "status": "owed", "note": note}
                    self._note(run, note)
                if self._texts_left(run.store_id) < len(wave):
                    self._note(run, f"Outreach stopped: text limit reached ({self.max_texts_per_hour} per store per hour).")
                    run.state.status, run.state.current_rank = "exhausted", None
                    break
                run.waiting = {}
                solo = pol.mode == "group_offer" and len(wave) < pol.min_recipients
                for c in wave:
                    # never call a single text a mass communication
                    extra = [predictive.VOLUNTARY] if solo else list(pol.sentences)
                    if "voluntary" in (c.why or "").lower() and not any("voluntary" in x for x in extra):
                        extra.append(predictive.VOLUNTARY)  # SEMANTICS #17: plan says exempt as voluntary
                    if await self._send(run, emps[c.employee_id], offer_text(config, c, extra), c.rank):
                        _drop_queued(run, emps[c.employee_id].phone)  # earlier replies were to an older offer
                        run.waiting[emps[c.employee_id].phone] = (emps[c.employee_id], c)
                        run.texted += 1
                    else:
                        run.declined.append(c.employee_id)
                if not run.waiting:
                    queue = await self._refix(run, config)
                    self._persist(run)
                    continue
                run.state.wave += 1
                self._sync_waiting(run)
                self._persist(run)
                for phone, (_, c) in list(run.waiting.items()):
                    self._start_auto(run, phone, c)

                queue, accepted_any = await self._await_wave(run, config, queue)
                self._stop_auto(run)
                for _, c in run.waiting.values():  # no answer before the timeout
                    run.declined.append(c.employee_id)
                run.waiting = {}
                self._sync_waiting(run)
                if accepted_any and not queue:
                    run.state.status, run.state.current_rank = "filled", None
                    break
                if not accepted_any:
                    queue = await self._refix(run, config)
                self._persist(run)
        except asyncio.CancelledError:
            self._stop_auto(run)
            raise
        except Exception as e:  # noqa: BLE001 - surface in state rather than dying silently
            run.state.status = "exhausted"
            self._note(run, f"Outreach stopped: {e}")
        finally:
            self._persist(run)

    @staticmethod
    def _sync_waiting(run: Run) -> None:
        run.state.waiting_employee_ids = [e.id for e, _ in run.waiting.values()]
        run.state.current_rank = min((c.rank for _, c in run.waiting.values()), default=None)

    async def _accept(self, run: Run, config: StoreConfig, cand: OutreachCandidate) -> list[OutreachCandidate]:
        run.state.accepted_employee_ids.append(cand.employee_id)
        run.booked.append(cand.proposed_shift)
        run.schedule, report = await asyncio.to_thread(self._commit_shift, config, run.schedule, cand)
        run.state.schedule = run.schedule
        self.db.save_schedule(run.store_id, run.schedule, report)
        return await self._refix(run, config)

    async def _await_wave(self, run: Run, config: StoreConfig, queue: list[OutreachCandidate]):
        """Collect replies for the current wave (run.waiting) until everyone answered or the timeout.
        -> (latest queue, whether anyone accepted)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_s
        accepted_any = False
        while run.waiting:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                msg: InboundMessage = await asyncio.wait_for(run.replies.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            key = _waiting_key(run, msg.from_phone)
            if key is None:
                continue
            emp, cand = run.waiting[key]
            if msg.interpreted_as == "accept":
                run.waiting.pop(key)
                self._stop_auto(run, key)
                queue = await self._accept(run, config, cand)
                accepted_any = True
                still = {(c.employee_id, _shift_key(c)): c for c in queue}
                by_emp = {c.employee_id: c for c in queue}
                for k, (e, c) in list(run.waiting.items()):
                    match = still.get((c.employee_id, _shift_key(c)))
                    if match is not None:  # their shift is still needed: keep waiting on them
                        run.waiting[k] = (e, match)
                        continue
                    moved = by_emp.get(c.employee_id)
                    self._stop_auto(run, k)
                    if moved is not None:  # still needed, but the engine moved their shift: re-offer, ask again
                        extra = list((run.policy or predictive.Policy()).sentences)
                        await self._send(run, e, "Update: " + offer_text(config, moved, extra), moved.rank)
                        _drop_queued(run, k)  # a YES to the old times doesn't count for the new ones
                        run.waiting[k] = (e, moved)
                        self._start_auto(run, k, moved)
                        continue
                    run.waiting.pop(k)  # the shift they were offered is covered now
                    await self._send(run, e, FILLED_TEXT, c.rank)
                self._sync_waiting(run)
                self._persist(run)
                if not queue:
                    for k, (e, c) in list(run.waiting.items()):
                        await self._send(run, e, FILLED_TEXT, c.rank)
                    run.waiting = {}
                    break
            elif msg.interpreted_as == "decline":
                run.waiting.pop(key)
                run.declined.append(cand.employee_id)
                self._stop_auto(run, key)
                self._sync_waiting(run)
                self._persist(run)
            elif msg.interpreted_as == "question":
                await self._answer(run, config, emp, cand)
            # question / unknown: also in the leader's view (state.messages); keep waiting
        return queue, accepted_any

    # ---------------------------------------------------------------- simulated replies (mock only)
    def _script(self, run: Run, cand: OutreachCandidate) -> list[str]:
        if self.autoreply == "script":
            # demo: 1st person texted declines; 2nd asks a question, then accepts; anyone after accepts
            return {1: [SCRIPT_DECLINE], 2: [SCRIPT_QUESTION, SCRIPT_ACCEPT]}.get(run.texted, [SCRIPT_ACCEPT])
        if self.autoreply == "prob":
            rng = random.Random(f"{self.seed}:{run.plan_id}:{cand.employee_id}")
            return [SCRIPT_ACCEPT if rng.random() < cand.est_accept_prob else SCRIPT_DECLINE]
        return []

    def _start_auto(self, run: Run, phone: str, cand: OutreachCandidate) -> None:
        replies = self._script_for(run, cand)
        if not replies:
            return

        async def reply() -> None:
            for body in replies:
                await asyncio.sleep(self.reply_delay_s)
                if not _waiting_key(run, phone):
                    return
                await self.inbound(phone, body)
        run.auto_tasks[phone] = asyncio.create_task(reply())

    def _script_for(self, run: Run, cand: OutreachCandidate) -> list[str]:
        if self.autoreply != "script":
            return self._script(run, cand)
        ids = [c.employee_id for _, c in run.waiting.values()]
        nth = run.texted - len(ids) + ids.index(cand.employee_id) + 1  # 1-based send order in this outreach
        return {1: [SCRIPT_DECLINE], 2: [SCRIPT_QUESTION, SCRIPT_ACCEPT]}.get(nth, [SCRIPT_ACCEPT])

    @staticmethod
    def _stop_auto(run: Run, phone: Optional[str] = None) -> None:
        for k in ([phone] if phone else list(run.auto_tasks)):
            t = run.auto_tasks.pop(k, None) if k else None
            if t and not t.done() and t is not asyncio.current_task():
                t.cancel()

    async def _answer(self, run: Run, config: StoreConfig, emp, cand: OutreachCandidate) -> None:
        if self._texts_left(run.store_id) <= 0:
            return
        if await self._send(run, emp, answer_text(config, cand), cand.rank):
            self._persist(run)

    def _commit_shift(self, config: StoreConfig, schedule: Schedule, cand: OutreachCandidate):
        """Add the accepted shift, re-validate (with the law pack) and return (schedule, report | None)."""
        sched = schedule.model_copy(deep=True)
        sched.shifts.append(cand.proposed_shift)
        return validated(config, sched)

    async def _refix(self, run: Run, config: StoreConfig) -> list[OutreachCandidate]:
        # plan against the same posted schedule as the first fix, plus the call-ins booked so far (the saved
        # schedule already has the plan's actions applied; planning on it would count them twice)
        base = run.posted or run.schedule
        planned = base.model_copy(update={"shifts": list(base.shifts) + list(run.booked)}) if run.posted else base
        req = FixRequest(config=with_law_pack(config), schedule=planned, callouts=run.callouts, day=run.day,
                         now=run.now, declined_employee_ids=list(run.declined),
                         outreach_mode=(run.policy.mode if run.policy else None))
        plan = await asyncio.to_thread(integrations.fix_day, req)
        accepted = set(run.state.accepted_employee_ids)
        if run.state.premium is not None:  # latest pricing for people not yet booked; booked keep theirs
            by_emp = {b["employee_id"]: b for b in run.state.premium.get("by_employee", [])}
            for b in premium_breakdown(plan):
                if b["employee_id"] not in accepted:
                    by_emp[b["employee_id"]] = b
            run.state.premium["by_employee"] = list(by_emp.values())
        return [c for c in plan.outreach_queue if c.employee_id not in accepted]


def validated(config: StoreConfig, sched: Schedule):
    """Validate, adopt the validator's recomputed metrics, and validate again so the saved report doesn't
    flag the stale metrics. -> (schedule, report | None)."""
    sched = sched.model_copy(deep=True)
    try:
        cfg = with_law_pack(config)
        report = integrations.validate(cfg, sched)
        if report.recomputed_metrics is not None:
            sched.metrics = report.recomputed_metrics
            report = integrations.validate(cfg, sched)
        return sched, report
    except integrations.StubUnavailable:
        return sched, None  # validator not merged: keep previous metrics rather than invent new ones


def premium_breakdown(plan: FixPlan) -> list[dict]:
    """Per-candidate predictive-scheduling premium as the engine priced it (receipt line items)."""
    return [{"employee_id": c.employee_id, "premium_pay_dollars": c.premium_pay_dollars,
             "law_rule_ids": list(c.law_rule_ids), "note": c.premium_note} for c in plan.outreach_queue]


def with_law_pack(config: StoreConfig) -> StoreConfig:
    if config.law_pack is not None:
        return config
    cfg = config.model_copy(deep=True)
    cfg.law_pack = integrations.resolve_law(cfg.store.jurisdiction)
    return cfg


def _drop_queued(run: Run, phone: str) -> None:
    """Forget replies from `phone` that arrived before its latest offer."""
    keep = []
    while not run.replies.empty():
        m = run.replies.get_nowait()
        if not _same_phone(m.from_phone, phone):
            keep.append(m)
    for m in keep:
        run.replies.put_nowait(m)


def _shift_key(c: OutreachCandidate) -> tuple:
    sh = c.proposed_shift
    return (sh.day, sh.start, sh.end, tuple((g.role_id, g.start, g.end) for g in sh.segments))


def _waiting_key(run: Run, phone: str) -> Optional[str]:
    return next((k for k in run.waiting if _same_phone(k, phone)), None)


def _same_phone(a: str, b: str) -> bool:
    da, db_ = "".join(ch for ch in a if ch.isdigit()), "".join(ch for ch in b if ch.isdigit())
    return bool(da) and da[-10:] == db_[-10:]
