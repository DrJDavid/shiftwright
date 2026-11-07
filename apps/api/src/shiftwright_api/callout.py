"""Call-outs that arrive as messages: "can't make it tomorrow, I'm sick" -> repair the day and start offers.

An inbound message that isn't a reply to a shift offer comes here. We find who sent it (by phone, in the
store the employee page names, or any store with that number), decide whether it's a call-out and for which
shift (the LLM reads it against the person's own shifts; keywords are the fallback), then run the same
fix_day -> save_plan -> outreach path the manager's Fix tab uses. The manager sees it live and can stop it.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from shiftwright_contracts.models import CallOut, FixRequest, InboundMessage, Schedule, Shift, StoreConfig

from . import integrations, predictive
from .db import Database, NotFound
from .explain import DAYS, clock

KV = ("callout", "latest")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CALLOUT = re.compile(
    r"\b(sick|ill|fever|flu|covid|throwing up|vomit|hospital|emergency|call(ing)? (out|in sick)|"
    r"can'?t (make|come|work|do|go)|cannot (make|come|work)|won'?t (make|be (in|there|able))|"
    r"not (coming|going to make|gonna make|able to (come|make|work))|car (broke|died|won'?t))", re.I)


def _digits(phone: str) -> str:
    d = "".join(ch for ch in phone if ch.isdigit())
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def local_now(config: StoreConfig, at: Optional[datetime] = None) -> tuple[int, int]:
    """(weekday 0=Mon, minute of day) in the store's timezone."""
    try:
        tz = ZoneInfo(config.store.timezone or "America/Chicago")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("America/Chicago")
    t = (at or datetime.now(timezone.utc)).astimezone(tz)
    return t.weekday(), t.hour * 60 + t.minute


def find_sender(db: Database, from_phone: str, store_id: Optional[str] = None):
    """(store_id, config, employee) for this phone, or None. A named store wins; else the most recently
    updated store with that number."""
    want = _digits(from_phone)
    if not want:
        return None
    ids = [store_id] if store_id else [r[0] for r in db._q("SELECT id FROM stores ORDER BY updated_at DESC")]
    for sid in ids:
        try:
            cfg = db.get_config(sid)
        except Exception:  # noqa: BLE001
            continue
        emp = next((e for e in cfg.employees if e.phone and _digits(e.phone) == want), None)
        if emp:
            return sid, cfg, emp
    return None


def upcoming(shifts: list[Shift], today: int, now: int) -> list[Shift]:
    """The person's shifts from now on, wrapping around the week (the posted week repeats)."""
    def key(s: Shift) -> tuple[int, int]:
        ahead = (s.day - today) % 7
        if ahead == 0 and s.end <= now:
            ahead = 7  # today's shift is already over
        return ahead, s.start
    return sorted(shifts, key=key)


def day_named(text: str, today: int) -> Optional[int]:
    t = text.lower()
    if re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        return today
    if re.search(r"\b(tomorrow|tmrw|tmr)\b", t):
        return (today + 1) % 7
    for word in re.findall(r"[a-z]+", t.replace("weds", "wed")):  # mon, tues, thurs, saturday...
        for i, name in enumerate(WEEKDAYS):
            if len(word) >= 3 and name.startswith(word):
                return i
    return None


def describe(config: StoreConfig, s: Shift) -> str:
    roles = {r.id: r.name for r in config.roles}
    role = roles.get(s.segments[0].role_id, s.segments[0].role_id) if s.segments else ""
    return f"{DAYS[s.day]} {clock(s.start)}–{clock(s.end)}" + (f" ({role})" if role else "")


async def read_message(llm, config: StoreConfig, body: str, shifts: list[Shift], today: int) -> dict:
    """{"callout": bool, "shift": Shift | None, "how": "llm" | "keywords"}. The LLM picks from the person's own
    shifts; anything it says outside that list is ignored."""
    if llm is not None and shifts:
        listing = "\n".join(f"{i}: {describe(config, s)}" for i, s in enumerate(shifts))
        try:
            resp = await llm.complete([{"role": "user", "content": (
                f"An employee texted their workplace. Today is {WEEKDAYS[today].title()}.\n"
                f"Message: {json.dumps(body)}\n"
                f"Their upcoming shifts (soonest first):\n{listing}\n"
                "Are they saying they can't work a shift (a call-out)? Reply with JSON only: "
                '{"callout": true|false, "shift": <number from the list, or null if unclear>}')}], [])
            m = re.search(r"\{.*\}", resp.content or "", re.S)
            if m:
                data = json.loads(m.group(0))
                if isinstance(data.get("callout"), bool):
                    i = data.get("shift")
                    pick = shifts[i] if isinstance(i, int) and 0 <= i < len(shifts) else None
                    if data["callout"] and pick is None:
                        pick = _keyword_shift(body, shifts, today)
                    return {"callout": data["callout"], "shift": pick, "how": "llm"}
        except Exception:  # noqa: BLE001 - fall back to keywords
            pass
    if not _CALLOUT.search(body):
        return {"callout": False, "shift": None, "how": "keywords"}
    return {"callout": True, "shift": _keyword_shift(body, shifts, today), "how": "keywords"}


def _keyword_shift(body: str, shifts: list[Shift], today: int) -> Optional[Shift]:
    day = day_named(body, today)
    if day is not None:
        return next((s for s in shifts if s.day == day), None)
    return shifts[0] if shifts else None


def latest(db: Database, store_id: str) -> Optional[dict]:
    return db.get(store_id, *KV)


async def handle(app_state: Any, from_phone: str, body: str, store_id: Optional[str] = None,
                 at: Optional[datetime] = None) -> Optional[dict]:
    """Act on a message that wasn't a reply to an offer. Returns the recorded call-out (also saved under
    kv callout/latest for the manager's Fix tab), or None when the sender isn't on any roster."""
    db: Database = app_state.db
    mgr = app_state.outreach
    found = find_sender(db, from_phone, store_id)
    if not found:
        return None
    sid, cfg, emp = found
    today, now = local_now(cfg, at)
    rec: dict = {"id": "co_" + uuid.uuid4().hex[:8], "employee_id": emp.id, "employee_name": emp.name,
                 "body": body, "at": (at or datetime.now(timezone.utc)).isoformat(), "status": "not_a_callout",
                 "shift": None, "plan_id": None, "note": ""}
    try:
        sched, _ = db.latest_schedule(sid)
    except NotFound:
        sched = None
    mine = upcoming([s for s in (sched.shifts if sched else []) if s.employee_id == emp.id], today, now)
    read = await read_message(mgr.llm, cfg, body, mine, today)
    rec["read_by"] = read["how"]
    reply: Optional[str] = None
    if not read["callout"]:
        rec["note"] = "Not a call-out; passed to the manager."
    elif sched is None or not mine:
        rec["status"] = "no_shift"
        rec["note"] = f"{emp.name} called out, but has no shifts on the posted schedule."
        reply = "Got it. I don't see an upcoming shift for you on the posted schedule; your manager has your message."
    elif read["shift"] is None:
        rec["status"] = "unclear"
        rec["note"] = "Call-out, but no shift on the day they named."
        reply = ("Sorry to hear that. Which shift do you mean? You're on: "
                 + "; ".join(describe(cfg, s) for s in mine[:3]) + ".")
    else:
        shift: Shift = read["shift"]
        rec["shift"] = {"id": shift.id, "day": shift.day, "start": shift.start, "end": shift.end,
                        "label": describe(cfg, shift)}
        fix_now = now if shift.day == today else 0
        rec["day"], rec["now"] = shift.day, fix_now
        rec["status"], reply = await _repair(app_state, sid, cfg, sched, emp, shift, fix_now, rec)
    rec["reply"] = reply
    db.put(sid, *KV, rec)
    await _tell(app_state, sid, emp, from_phone, body, reply, rec)
    return {**rec, "store_id": sid}


async def _repair(app_state: Any, sid: str, cfg: StoreConfig, sched: Schedule, emp, shift: Shift, now: int,
                  rec: dict) -> tuple[str, str]:
    mgr = app_state.outreach
    run = mgr.runs.get(sid)
    if run and run.task and not run.task.done():
        rec["note"] = "Another call-out is already being covered; the manager will handle this one."
        return "queued", (f"Got it, you're out for {describe(cfg, shift)}. Your manager has been told.")
    from .agent.tools import with_law  # here: agent.tools imports a lot
    law_cfg = with_law(cfg)
    callout = CallOut(employee_id=emp.id, day=shift.day, reported_at=now)
    req = FixRequest(config=law_cfg, schedule=sched, callouts=[callout], day=shift.day, now=now,
                     outreach_mode=predictive.preferred_mode(law_cfg, law_cfg.law_pack))
    try:
        plan = await asyncio.to_thread(integrations.fix_day, req)
    except Exception as e:  # noqa: BLE001
        rec["note"] = f"Couldn't plan coverage automatically ({e}); the manager will handle it."
        return "failed", f"Got it, you're out for {describe(cfg, shift)}. Your manager has been told."
    plan = mgr.save_plan(sid, plan, [callout], shift.day, now, sched)
    rec["plan_id"] = plan.plan_id
    rec["texting"] = bool(plan.outreach_queue)
    if plan.outreach_queue:
        await mgr.start(sid, plan.plan_id)
        rec["note"] = f"Planned coverage and started offers ({len(plan.outreach_queue)} people ranked)."
        next_step = "I'm finding someone to cover and your manager can see it."
    else:
        await asyncio.to_thread(mgr.apply_plan, sid, plan.plan_id)
        rec["note"] = "Covered without calling anyone in (moves and extensions only)."
        next_step = "Your shift is covered and your manager can see it."
    # A call-out frees the rest of that day (CallOut is per day), so name every shift they're now off.
    off = sorted((s for s in sched.shifts if s.employee_id == emp.id and s.day == shift.day and s.end > now),
                 key=lambda s: s.start)
    when = f"{DAYS[shift.day]} " + ", ".join(f"{clock(s.start)}–{clock(s.end)}" for s in off) if off \
        else describe(cfg, shift)
    rec["off"] = when
    return "covering", f"Got it, feel better. You're off {when}. {next_step}"


async def _tell(app_state: Any, sid: str, emp, from_phone: str, body: str, reply: Optional[str], rec: dict) -> None:
    """Put the employee's message (and our reply, if any) in the live thread the Fix tab and employee page show."""
    mgr = app_state.outreach
    inbound = InboundMessage(id="in_" + uuid.uuid4().hex[:10], from_phone=from_phone, body=body,
                             received_at=datetime.now(timezone.utc), interpreted_as="unknown")
    app_state.db.log_message(inbound.id, sid, "in", inbound.model_dump(mode="json"))
    run = mgr.runs.get(sid)
    out = None
    if reply:
        try:
            out = await app_state.messenger.send(emp, reply)
            app_state.db.log_message(out.id, sid, "out", out.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001 - blocked or failed: the manager still sees the call-out
            rec["note"] += f" (Reply not sent: {e})"
            app_state.db.put(sid, *KV, rec)
    if run is not None and run.plan_id == rec.get("plan_id"):
        run.state.messages[:0] = [m for m in (inbound, out) if m is not None]
        mgr._persist(run)
