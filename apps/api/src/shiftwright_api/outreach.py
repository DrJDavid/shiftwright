"""Outreach orchestrator: text call-in candidates one at a time for a FixPlan.

rank 1 -> wait (timeout) -> accept: commit their shift, recompute, re-run fix_day to see whether
more coverage is still needed -> decline/timeout: add to declined_employee_ids, re-run fix_day,
text the next. Stops when fix_day's queue is empty after an accept (filled) or no one is left (exhausted).
"""
from __future__ import annotations

import asyncio
import uuid
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
from .explain import DAYS, hhmm
from .messenger import Messenger, interpret
from .models import OutreachState


def offer_text(config: StoreConfig, cand: OutreachCandidate) -> str:
    emp = next(e for e in config.employees if e.id == cand.employee_id)
    sh = cand.proposed_shift
    roles = {r.id: r.name for r in config.roles}
    role_names = ", ".join(dict.fromkeys(roles.get(s.role_id, s.role_id) for s in sh.segments)) or "a shift"
    first = emp.name.split(" ")[0]
    return (f"Hi {first}, {config.store.name} needs {role_names} {DAYS[sh.day]} {hhmm(sh.start)}-{hhmm(sh.end)} "
            f"at ${emp.wage_per_hour:.2f}/hr. Can you work it? Reply YES or NO")


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
    current_phone: Optional[str] = None
    task: Optional[asyncio.Task] = None


class OutreachManager:
    def __init__(self, db: Database, messenger: Messenger, llm, timeout_s: float):
        self.db, self.messenger, self.llm, self.timeout_s = db, messenger, llm, timeout_s
        self.runs: dict[str, Run] = {}

    # ---------------------------------------------------------------- plans
    def save_plan(self, store_id: str, plan: FixPlan, callouts: list[CallOut], day: int, now: int,
                  schedule: Schedule) -> str:
        plan_id = "plan_" + uuid.uuid4().hex[:10]
        self.db.put(store_id, "fix_plan", plan_id, {
            "plan": plan.model_dump(mode="json"), "callouts": [c.model_dump(mode="json") for c in callouts],
            "day": day, "now": now, "schedule": schedule.model_dump(mode="json")})
        return plan_id

    def state(self, store_id: str) -> OutreachState:
        run = self.runs.get(store_id)
        if run:
            return run.state
        saved = self.db.get(store_id, "outreach", "state")
        return OutreachState.model_validate(saved) if saved else OutreachState()

    def _persist(self, run: Run) -> None:
        self.db.put(run.store_id, "outreach", "state", run.state.model_dump(mode="json"))

    # ---------------------------------------------------------------- start
    async def start(self, store_id: str, plan_id: str) -> OutreachState:
        saved = self.db.get(store_id, "fix_plan", plan_id)
        if not saved:
            raise KeyError(plan_id)
        old = self.runs.get(store_id)
        if old and old.task and not old.task.done():
            old.task.cancel()
        plan = FixPlan.model_validate(saved["plan"])
        schedule = Schedule.model_validate(saved["schedule"])
        run = Run(store_id=store_id, plan_id=plan_id, plan=plan,
                  callouts=[CallOut.model_validate(c) for c in saved["callouts"]], day=saved["day"],
                  now=saved["now"], schedule=schedule,
                  state=OutreachState(plan_id=plan_id, status="texting", schedule=schedule))
        self.runs[store_id] = run
        run.task = asyncio.create_task(self._run(run))
        await asyncio.sleep(0)  # let the first text go out
        return run.state

    # ---------------------------------------------------------------- inbound
    async def inbound(self, from_phone: str, body: str) -> Optional[InboundMessage]:
        run = next((r for r in self.runs.values() if r.current_phone and _same_phone(r.current_phone, from_phone)
                    and r.state.status == "texting"), None)
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
    async def _run(self, run: Run) -> None:
        queue = list(run.plan.outreach_queue)
        try:
            while True:
                cand = next((c for c in sorted(queue, key=lambda c: c.rank)
                             if c.employee_id not in run.declined
                             and c.employee_id not in run.state.accepted_employee_ids), None)
                if cand is None:
                    run.state.status = "exhausted"
                    run.state.current_rank = None
                    break
                config = self.db.get_config(run.store_id)
                emp = next(e for e in config.employees if e.id == cand.employee_id)
                out = await self.messenger.send(emp, offer_text(config, cand), outreach_rank=cand.rank)
                self.db.log_message(out.id, run.store_id, "out", out.model_dump(mode="json"))
                run.current_phone = emp.phone
                run.state.current_rank = cand.rank
                run.state.messages.append(out)
                self._persist(run)

                verdict = await self._await_verdict(run)
                run.current_phone = None
                if verdict == "accept":
                    run.state.accepted_employee_ids.append(cand.employee_id)
                    run.schedule = await asyncio.to_thread(self._commit_shift, config, run.schedule, cand)
                    run.state.schedule = run.schedule
                    self.db.save_schedule(run.store_id, run.schedule, None)
                    queue = await self._refix(run, config)
                    if not queue:
                        run.state.status = "filled"
                        run.state.current_rank = None
                        break
                else:  # decline / timeout
                    run.declined.append(cand.employee_id)
                    queue = await self._refix(run, config)
                self._persist(run)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - surface in state rather than dying silently
            run.state.status = "exhausted"
            run.state.messages.append(InboundMessage(
                id="sys_" + uuid.uuid4().hex[:8], from_phone="system", body=f"Outreach stopped: {e}",
                received_at=datetime.now(timezone.utc), interpreted_as="unknown"))
        finally:
            self._persist(run)

    async def _await_verdict(self, run: Run) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_s
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return "timeout"
            try:
                msg: InboundMessage = await asyncio.wait_for(run.replies.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return "timeout"
            if msg.interpreted_as in ("accept", "decline"):
                return msg.interpreted_as
            # question / unknown: forwarded to the leader's view (it's in state.messages); keep waiting

    def _commit_shift(self, config: StoreConfig, schedule: Schedule, cand: OutreachCandidate) -> Schedule:
        sched = schedule.model_copy(deep=True)
        sched.shifts.append(cand.proposed_shift)
        try:
            report = integrations.validate(config, sched)
            sched.metrics = report.recomputed_metrics
        except integrations.StubUnavailable:
            pass  # validator not merged: keep previous metrics rather than invent new ones
        return sched

    async def _refix(self, run: Run, config: StoreConfig) -> list[OutreachCandidate]:
        req = FixRequest(config=config, schedule=run.schedule, callouts=run.callouts, day=run.day, now=run.now,
                         declined_employee_ids=list(run.declined))
        plan = await asyncio.to_thread(integrations.fix_day, req)
        return [c for c in plan.outreach_queue if c.employee_id not in run.state.accepted_employee_ids]


def _same_phone(a: str, b: str) -> bool:
    da, db_ = "".join(ch for ch in a if ch.isdigit()), "".join(ch for ch in b if ch.isdigit())
    return bool(da) and da[-10:] == db_[-10:]
