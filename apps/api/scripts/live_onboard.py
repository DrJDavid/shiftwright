"""Live onboarding rehearsal: the real agent model onboards the demo store from template `empty`.

A simulated leader speaks the demo narrative and answers every card from the demo fixture's config
(packages/scenarios/fixtures/demo_scenario.json). Uses OPENROUTER_API_KEY / AGENT_MODEL from env.

    set -a; . ./.env; set +a; uv run python apps/api/scripts/live_onboard.py [--turns 8] [--out log.json]

Prints each turn's assistant text, the tool sequence, failing readiness checks, and a final verdict.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from shiftwright_api.agent.llm import OpenRouterClient
from shiftwright_api.agent.loop import run_turn
from shiftwright_api.db import Database
from shiftwright_api import equipment, readiness, templates
from shiftwright_api.settings import Settings
from shiftwright_contracts.models import Jurisdiction, StoreConfig

REPO = Path(__file__).resolve().parents[3]
SCENARIO = REPO / "packages/scenarios/fixtures/demo_scenario.json"
FOLLOW_UPS = [
    "Yes. I have our roster export as a CSV if that helps. No corporate forecast though.",
    "Go ahead, keep going with whatever is still missing.",
    "Sounds right. What's next?",
    "Keep going.",
]


class Counting(OpenRouterClient):
    steps = 0
    prompt_chars = 0

    async def stream(self, messages, tools):
        Counting.steps += 1
        Counting.prompt_chars += len(json.dumps(messages)) + len(json.dumps(tools))
        async for p in super().stream(messages, tools):
            yield p


def staffing_from_target(t: dict, role_id: str, groups: list[dict]) -> dict:
    """The simulated leader describes the fixture's demand as base + peaks + open crew (approximately)."""
    slot = t["store"]["slot_minutes"]
    hours = {h["day"]: h for h in t["store"]["hours"]}

    def profile(day: int) -> dict[int, int]:
        prof: dict[int, int] = {}
        for dm in t["demand"]:
            if dm["role_id"] == role_id and dm["day"] == day:
                for m in range(dm["start"], dm["end"], slot):
                    prof[m] = prof.get(m, 0) + dm["headcount"]
        return prof
    ref = groups[0]["days"][0] if groups else 0
    h = hours.get(ref, {"open": 480, "close": 1320})
    prof = profile(ref)
    inside = [prof.get(m, 0) for m in range(h["open"], h["close"], slot)]
    base = max(set(inside), key=inside.count) if inside else 0
    peaks = []
    for g in groups:
        d = g["days"][0]
        hd = hours.get(d, h)
        p = profile(d)
        m = hd["open"]
        while m < hd["close"]:
            n = p.get(m, 0)
            if n != base:
                s = m
                while m < hd["close"] and p.get(m, 0) == n:
                    m += slot
                peaks.append({"day_group": g["id"], "start": s, "end": m, "headcount": n})
            else:
                m += slot
    before = [p for m, p in prof.items() if m < h["open"]]
    op = {"headcount": max(before), "minutes_before_open": h["open"] - min(m for m in prof if m < h["open"])} \
        if before else None
    return {"base": base, "peaks": peaks, "open": op, "close": None}


def leader_cards(db: Database, store_id: str, target: StoreConfig, log: list):
    t = target.model_dump(mode="json")
    rules_by_kind: dict[str, list[dict]] = {}
    for c in t["constraints"]:
        rules_by_kind.setdefault(c["kind"], []).append(c)

    async def wait(card_id: str, card_type: str, props: dict) -> dict:
        cur = db.get_config(store_id)
        ans: dict
        if card_type == "store_basics":
            ans = {k: v for k, v in t["store"].items() if k not in ("id", "week_start")}
        elif card_type == "payroll":
            ans = {k: v for k, v in t["budget"].items() if k != "approvals"}
        elif card_type == "roles":
            ans = {"departments": t["departments"], "roles": t["roles"]}
        elif card_type == "csv_import":
            role_ids = {r.id for r in cur.roles}
            emps = [dict(e, trained_role_ids=[r for r in e["trained_role_ids"] if r in role_ids])
                    for e in t["employees"]]
            if props.get("kind", "roster") in ("roster", "training", "availability"):
                db.mutate(store_id, lambda d: d.update(employees=emps), "import:roster", {"rows": len(emps)}, "leader")
                ans = {"committed": True, "kind": props.get("kind", "roster"), "rows": len(emps)}
            else:
                ans = {"committed": False, "rows": 0, "note": "No such file."}
        elif card_type == "training_matrix":
            ans = {e["id"]: e["trained_role_ids"] for e in t["employees"] if e["id"] in {x.id for x in cur.employees}}
        elif card_type == "coverage_grid":
            days, start, slot = props.get("days") or [], props["start_minute"], props["slot_minutes"]
            ref = days[0] if days else 0
            grid = {r: [0] * len(v) for r, v in props["prefill"].items()}
            for dm in t["demand"]:
                if dm["day"] == ref and dm["role_id"] in grid:  # leader enters event crews on the grid too
                    for i in range(len(grid[dm["role_id"]])):
                        if dm["start"] <= start + i * slot < dm["end"]:
                            grid[dm["role_id"]][i] += dm["headcount"]
            ans = {"grid": grid}
        elif card_type == "department_staffing":
            ans = {"staffing": {r["id"]: staffing_from_target(t, r["id"], props["day_groups"])
                                for r in props["roles"]}}
        elif card_type == "events":
            ans = {"events": t["events"]}
        elif card_type == "confirm_tags":
            ans = {"decisions": {r["role_id"]: "keep" for r in props["roles"]}}
        elif card_type == "propose_rule":
            kind = props["constraint"]["kind"]
            match = (rules_by_kind.get(kind) or [None])[0]
            if match is None:
                ans = {"decision": "soft", "weight_dollars": 10}
            elif match["strength"] == "hard":
                ans = {"decision": "hard"}
            else:
                ans = {"decision": "soft", "weight_dollars": match["weight_dollars"] or 10}
        elif card_type == "employee_availability":
            ans = {"confirmed": props.get("parsed") or []}
        else:  # tradeoff / conflict_menu: the leader declines to choose in this rehearsal
            ans = {"cancelled": True}
        log.append({"card": card_type, "props_keys": list(props), "answer_keys": list(ans)[:8]})
        print(f"    [card] {card_type} -> {', '.join(list(ans)[:6])}")
        return ans
    return wait


async def main(turns: int, out: str | None) -> int:
    scenario = json.loads(SCENARIO.read_text())
    target = StoreConfig.model_validate(scenario["config"])
    s = Settings.from_env()
    if not s.openrouter_api_key:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    db = Database(str(Path(tempfile.mkdtemp()) / "live.db"))
    cfg = db.create_store(templates.build("empty", "Store #0417", Jurisdiction(state="TX", city="austin")))
    sid = cfg.store.id
    llm = Counting(s.openrouter_api_key, s.agent_model)
    log: list = []
    waiter = leader_cards(db, sid, target, log)
    t0 = time.time()
    messages = [scenario["narrative"] + "\n\nHelp me get this store set up."] + FOLLOW_UPS
    ready = False
    for n, text in enumerate(messages[:turns]):
        print(f"\n=== leader: {text[:120]}{'…' if len(text) > 120 else ''}")
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
        print("  agent:", "".join(texts).strip()[:1500])
        log.append({"turn": n, "tools": tools, "text": "".join(texts)})
        rd = readiness.compute(db.get_config(sid), equipment.state(db, sid))
        failing = [c.id for c in rd.checks if not c.ok]
        print("  readiness:", "READY" if rd.ready else f"failing {failing}")
        if rd.ready:
            ready = True
            break
    final = db.get_config(sid)
    print(f"\nready={ready} turns={n + 1} llm_steps={Counting.steps} prompt_chars≈{Counting.prompt_chars:,} "
          f"time={time.time() - t0:.0f}s constraints={[(c.kind.value, c.strength.value, c.status.value) for c in final.constraints]} "
          f"unmodeled={[u.text for u in final.unmodeled]}")
    if out:
        Path(out).write_text(json.dumps({"log": log, "transcript": db.get_transcript(sid)}, indent=1, default=str))
    return 0 if ready else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.turns, a.out)))
