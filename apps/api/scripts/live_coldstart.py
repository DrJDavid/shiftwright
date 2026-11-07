"""Live cold-start rehearsal (contracts v1.5): chat only, no CSVs, "a 30-seat taqueria in Chicago".

The real agent model onboards from template `empty`. A simulated owner answers in plain chat and
confirms every card as the agent drafted it (that is the napkin flow: the agent drafts, the owner
confirms). Uses OPENROUTER_API_KEY / AGENT_MODEL from env.

    set -a; . ./.env; set +a; uv run python apps/api/scripts/live_coldstart.py [--turns 8] [--out log.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from shiftwright_api import equipment, readiness, templates
from shiftwright_api.agent.llm import OpenRouterClient
from shiftwright_api.agent.loop import run_turn
from shiftwright_api.db import Database
from shiftwright_api.settings import Settings
from shiftwright_contracts.models import Jurisdiction

OWNER = [
    "Hi! I run a 30-seat taqueria in Chicago, Pilsen. Family place, about 10 people on staff.",
    "We're closed Mondays. Tuesday to Thursday 11am-9pm, Friday and Saturday 11am-11pm, Sunday 10am-8pm. "
    "I usually schedule about 330 hours a week total. Roles: line cook, prep, dishwasher, server, host, "
    "bartender, and a manager on duty. Servers and the bartender get tips: on tipped shifts I pay them the "
    "tipped cash wage, $13.00 an hour, and their regular rate for anything else. "
    "We have a fryer for chips and taquitos, the line cooks run it.",
    "Staff (phones are all 312-555-01xx): Maria Lopez, 45, manager, $26/h, 312-555-0101. "
    "Luis Ortega, 34, line cook, $19, 312-555-0102. Ana Ruiz, 28, line cook and prep, $18, 312-555-0103. "
    "Jose Diaz, 19, prep and dishwasher, $17.50, 312-555-0104. Sofia Cruz, 22, server, $17.10, "
    "312-555-0105. Camila Reyes, 24, server and host, $17.10, 312-555-0106. Diego Flores, 17, host, $17.10, "
    "312-555-0107. Lupe Vargas, 30, bartender and server, $17.25, 312-555-0108. Kevin Ng, 15, dishwasher, "
    "$17.10, 312-555-0109. Tommy Ruiz, 15, line cook (he's trained on the fryer), $17.10, 312-555-0111. "
    "Rosa Medina, 52, line cook and prep, $20, 312-555-0110. Maria and Rosa can also "
    "be manager on duty.",
    "A normal week: lunch rush 12-2 on weekdays, Friday and Saturday dinners get slammed 6-9pm, Sunday brunch "
    "10-1 is busy. Normally 1 manager on duty always, 2 line cooks (3 on Fri/Sat dinner), 1 prep in the "
    "morning 10-2, 1 dishwasher (2 on Fri/Sat nights), 2 servers (4 at Fri/Sat dinner, 3 at Sunday brunch), "
    "1 host evenings 5-9, 1 bartender from 4pm to close. This Saturday 4-7pm we have a private rehearsal "
    "dinner that needs 2 extra servers. And our produce delivery comes Tuesday and Friday at 9am, 1 prep person "
    "unloads for an hour.",
    "Rules: shifts at least 4 hours. Kevin can't work before 4pm on school days. Keep both of those role tags, "
    "and yes, Tommy is trained on the fryer. Looks good, keep going.",
    "Yes, that's right. Go ahead.",
    "Yes. Keep going with whatever is missing.",
    "Sounds good.",
]


class Counting(OpenRouterClient):
    steps = 0
    prompt_chars = 0

    async def stream(self, messages, tools):
        Counting.steps += 1
        Counting.prompt_chars += len(json.dumps(messages)) + len(json.dumps(tools))
        async for p in super().stream(messages, tools):
            yield p


def owner_cards(log: list):
    async def wait(card_id: str, card_type: str, props: dict) -> dict:
        if card_type == "store_basics":
            ans = {k: v for k, v in props.items() if k not in ("id", "week_start")}
        elif card_type == "payroll":
            ans = {k: v for k, v in props.items() if k != "approvals"}
        elif card_type == "roles":
            ans = {"departments": props["departments"], "roles": props["roles"]}
        elif card_type == "training_matrix":
            ans = {e["id"]: e["trained_role_ids"] for e in props["employees"]}
        elif card_type == "department_staffing":
            ans = {"staffing": props["suggested"]}
        elif card_type == "events":
            ans = {"events": props["events"]}
        elif card_type == "propose_rule":
            ans = {"decision": "hard"}
        elif card_type == "employee_availability":
            ans = {"confirmed": props.get("parsed") or []}
        elif card_type == "coverage_grid":
            ans = {"grid": props.get("prefill") or {}}
        else:  # csv_import (no files), tradeoff, conflict_menu
            ans = {"cancelled": True}
        log.append({"card": card_type})
        print(f"    [card] {card_type}" + (f" ({props['department']['name']})" if card_type == "department_staffing" else ""))
        return ans
    return wait


async def main(turns: int, out: str | None) -> int:
    s = Settings.from_env()
    if not s.openrouter_api_key:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    db = Database(str(Path(tempfile.mkdtemp()) / "cold.db"))
    sid = db.create_store(templates.build("empty", "New business", Jurisdiction(state="IL", city="chicago"))).store.id
    llm = Counting(s.openrouter_api_key, s.agent_model)
    log: list = []
    waiter = owner_cards(log)
    t0, ready, n = time.time(), False, 0
    for n, text in enumerate(OWNER[:turns]):
        print(f"\n=== owner: {text[:110]}{'…' if len(text) > 110 else ''}")
        texts, tools = [], []
        async for ev, data in run_turn(db=db, llm=llm, store_id=sid, mode="onboard",
                                       user_messages=[{"role": "user", "content": text}], await_card=waiter):
            if ev == "text":
                texts.append(data["delta"])
            elif ev == "tool" and data["status"] == "start":
                tools.append(data["name"])
            elif ev == "tool" and data["status"] == "done" and "error" in data["summary"]:
                tools.append(f"!{data['summary']}")
            elif ev == "error":
                print("  ERROR:", data["message"])
        print("  tools:", ", ".join(tools))
        print("  agent:", "".join(texts).strip()[:1200])
        log.append({"turn": n, "tools": tools, "text": "".join(texts)})
        rd = readiness.compute(db.get_config(sid), equipment.state(db, sid))
        print("  readiness:", "READY" if rd.ready else f"failing {[c.id for c in rd.checks if not c.ok]}",
              "| warn:", [c.id for c in rd.checks if c.severity == "warn"])
        if rd.ready and n >= 5:
            ready = True
            break
    cfg = db.get_config(sid)
    print(f"\nready={ready} turns={n + 1} llm_steps={Counting.steps} prompt_chars≈{Counting.prompt_chars:,} "
          f"time={time.time() - t0:.0f}s")
    print("sector:", cfg.store.sector, "|", cfg.store.business_description)
    print("hours:", [(h.day, h.open, h.close) for h in cfg.store.hours])
    print("roles:", [(r.id, r.tipped) for r in cfg.roles], "tags:", cfg.role_tags)
    print("employees:", [(e.name, e.age, e.wage_per_hour, e.tipped_wage_per_hour, e.trained_role_ids) for e in cfg.employees])
    print("demand blocks:", len(cfg.demand), "sources:", sorted({d.source.value for d in cfg.demand}),
          "days:", sorted({d.day for d in cfg.demand}))
    print("events:", [(e.kind.value, e.label, e.day, e.start, e.end) for e in cfg.events])
    print("constraints:", [(c.kind.value, c.strength.value, c.status.value) for c in cfg.constraints],
          "unmodeled:", [u.text for u in cfg.unmodeled])
    print("budget:", cfg.budget.weekly_hours_cap)
    checks = {c.id: c for c in readiness.compute(cfg, equipment.state(db, sid)).checks}
    for cid in ("minimum_wage", "minors_on_tagged_roles", "equipment_roles", "business_type"):
        print(f"check {cid}: ok={checks[cid].ok} severity={checks[cid].severity} — {checks[cid].detail[:300]}")
    # solve + validate: the 15-year-old must never be on a role the law pack bars at their age
    from shiftwright_api import integrations
    from shiftwright_api.agent.tools import with_law
    full = with_law(cfg)
    t1 = time.time()
    sched = integrations.solve_week(full, time_limit_s=20)
    val = integrations.validate(full, sched)
    minors = {e.id: e for e in cfg.employees if e.age < 18}
    hits = [(minors[sh.employee_id].name, seg.role_id, sh.day, seg.start, seg.end) for sh in sched.shifts
            if sh.employee_id in minors for seg in sh.segments if set(cfg.role_tags.get(seg.role_id, []))]
    print(f"solve {time.time() - t1:.1f}s: {sched.status}, {len(sched.shifts)} shifts, coverage "
          f"{sched.metrics.coverage_pct:.1f}%, cost ${sched.metrics.total_wage_cost:,.2f}; validator passed={val.passed} "
          f"codes={sorted({v.code.value for v in val.violations if v.severity == 'hard'})}")
    print("minors on tagged roles in the schedule:", hits or "none")
    if out:
        Path(out).write_text(json.dumps({"log": log, "transcript": db.get_transcript(sid),
                                         "config": cfg.model_dump(mode="json")}, indent=1, default=str))
    return 0 if ready else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.turns, a.out)))
