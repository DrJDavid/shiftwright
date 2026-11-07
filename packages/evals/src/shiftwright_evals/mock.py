"""Mock baselines: canned bad outputs, for building and testing the harness without an API key.

These are NOT model results. Every report built from them says so in a banner. Each mock reads the
store config out of the prompt (like a real model would), builds a sloppy greedy schedule, and then
injects one failure kind, chosen deterministically from (model, prompt):

  hallucinated_employee  adds shifts for people who are not on the roster
  minor_on_forklift      puts the youngest employee on a min-age / prohibited role
  over_budget            schedules well past the weekly hours cap
  truncated              stops mid-JSON with finish_reason "length"
  unparseable            prose instead of JSON (the retry gets prose again)
  sloppy                 the greedy schedule as-is (no breaks, ignores availability and hours)
  claims_infeasible      says "infeasible" without a reason grounded in the config

Infeasible stores are never detected by the mocks, so they confidently return a "feasible" schedule
(the false-feasible failure the honesty suite measures).

Repair prompts get: ignored_callout, changed_past, or a superficially careful repair.
"""
from __future__ import annotations

import hashlib
import json
import re

WEEKLY_KINDS = {
    "mock-a": ["hallucinated_employee", "over_budget", "sloppy", "truncated", "minor_on_forklift", "unparseable"],
    "mock-b": ["minor_on_forklift", "sloppy", "unparseable", "hallucinated_employee", "claims_infeasible",
               "over_budget", "truncated"],
}
REPAIR_KINDS = ["ignored_callout", "changed_past", "careful"]
MOCK_MODELS = ["mock-a", "mock-b"]


def _tag(text: str, name: str):
    m = re.search(rf"<{name}>\n(.*?)\n</{name}>", text, re.S)
    return json.loads(m.group(1)) if m else None


def _pick(model: str, text: str, kinds: list[str]) -> str:
    # Ignore contract_version so a contract bump doesn't reshuffle which canned failure each scenario gets.
    key = re.sub(r'"contract_version":\s*"[^"]*"', '"contract_version":"1.3.0"', text)
    h = int(hashlib.sha256((model + "|" + key).encode()).hexdigest(), 16)
    return kinds[h % len(kinds)]


def _fence(obj) -> str:
    return "Here is the schedule.\n\n```json\n" + json.dumps(obj, separators=(",", ":")) + "\n```\n"


def greedy(cfg: dict) -> list[dict]:
    """Chunk each demand block into <=8h shifts and hand them to trained people, fewest hours first."""
    trained = {r["id"]: [e for e in cfg["employees"] if r["id"] in e["trained_role_ids"]] for r in cfg["roles"]}
    hours: dict[str, float] = {e["id"]: 0.0 for e in cfg["employees"]}
    busy: dict[tuple[str, int], list[tuple[int, int]]] = {}
    shifts: list[dict] = []
    for d in sorted(cfg["demand"], key=lambda d: (d["day"], d["start"], d["role_id"])):
        t = d["start"]
        while t < d["end"]:
            end = min(d["end"], t + 480)
            if d["end"] - end < 180 and d["end"] - end > 0:
                end = d["end"]  # avoid a tiny tail
            pool = sorted(trained.get(d["role_id"], []), key=lambda e: (hours[e["id"]], e["id"]))
            placed = 0
            for e in pool:
                if placed >= d["headcount"]:
                    break
                spans = busy.setdefault((e["id"], d["day"]), [])
                if any(s < end and t < f for s, f in spans):
                    continue
                spans.append((t, end))
                hours[e["id"]] += (end - t) / 60
                shifts.append({"id": f"m{len(shifts) + 1}", "employee_id": e["id"], "day": d["day"],
                               "start": t, "end": end, "breaks": [],
                               "segments": [{"role_id": d["role_id"], "start": t, "end": end}]})
                placed += 1
            t = end
    return shifts


def _schedule(cfg: dict, shifts: list[dict], status: str = "feasible", infeasibility=None) -> dict:
    return {"store_id": cfg["store"]["id"], "week_start": cfg["store"]["week_start"],
            "config_version": cfg.get("config_version", 1), "produced_by": "baseline", "status": status,
            "shifts": shifts, "infeasibility": infeasibility}


def _restricted_role(cfg: dict) -> str | None:
    tagged = set(cfg.get("role_tags", {}))
    for r in cfg["roles"]:
        if r.get("min_age", 0) >= 18 or r["id"] in tagged:
            return r["id"]
    return None


def weekly(model: str, cfg: dict, text: str) -> tuple[str, str]:
    kind = _pick(model, text, WEEKLY_KINDS.get(model, WEEKLY_KINDS["mock-a"]))
    shifts = greedy(cfg)
    if kind == "unparseable":
        lines = [f"- {s['employee_id']}: day {s['day']} {s['start'] // 60}:00-{s['end'] // 60}:00" for s in shifts[:30]]
        return "Sure! Here's a balanced schedule for the week:\n\n" + "\n".join(lines) + "\n\n...and so on.", "stop"
    if kind == "truncated":
        full = json.dumps(_schedule(cfg, shifts), separators=(",", ":"))
        return "```json\n" + full[: max(200, len(full) * 3 // 5)], "length"
    if kind == "hallucinated_employee":
        for i, s in enumerate(list(shifts[:3])):
            shifts.append({**s, "id": f"mx{i}", "employee_id": f"e9{i:02d}",
                           "segments": [{**g} for g in s["segments"]]})
    elif kind == "minor_on_forklift":
        role = _restricted_role(cfg)
        kid = min(cfg["employees"], key=lambda e: (e["age"], e["id"]))
        if role:
            day = max(d["day"] for d in cfg["demand"])
            shifts.append({"id": "mkid", "employee_id": kid["id"], "day": day, "start": 360, "end": 600,
                           "breaks": [], "segments": [{"role_id": role, "start": 360, "end": 600}]})
    elif kind == "over_budget":
        cap = cfg["budget"]["weekly_hours_cap"]
        total = sum((s["end"] - s["start"]) / 60 for s in shifts)
        extra = 0
        for e in cfg["employees"]:
            if total > cap * 1.15:
                break
            for day in range(7):
                if total > cap * 1.15:
                    break
                role = e["trained_role_ids"][0]
                shifts.append({"id": f"mo{extra}", "employee_id": e["id"], "day": day, "start": 1080, "end": 1320,
                               "breaks": [], "segments": [{"role_id": role, "start": 1080, "end": 1320}]})
                extra += 1
                total += 4
    elif kind == "claims_infeasible":
        return _fence(_schedule(cfg, [], status="infeasible", infeasibility={
            "summary": "There are not enough staff to cover every shift this week."})), "stop"
    return _fence(_schedule(cfg, shifts)), "stop"


def repair(model: str, cfg: dict, current: dict, callouts: list[dict], text: str) -> tuple[str, str]:
    kind = _pick(model, text, REPAIR_KINDS)
    out = [dict(s) for s in current["shifts"]]
    gone = {(c["employee_id"], c["day"]) for c in callouts}
    day, now = callouts[0]["day"], callouts[0]["reported_at"]
    call_list = []
    if kind == "ignored_callout":
        call_list = [{"rank": 1, "employee_id": "e999", "role_id": cfg["roles"][0]["id"], "start": now, "end": now + 240,
                      "why": "Most reliable associate."}]
    else:
        out = [s for s in out if (s["employee_id"], s["day"]) not in gone]
        working = {s["employee_id"] for s in out if s["day"] == day} | {eid for eid, _ in gone}
        lost = [s for s in current["shifts"] if (s["employee_id"], s["day"]) in gone]
        for i, s in enumerate(lost):
            role = s["segments"][0]["role_id"] if s["segments"] else cfg["roles"][0]["id"]
            cand = next((e for e in cfg["employees"] if role in e["trained_role_ids"] and e["id"] not in working), None)
            if cand is None:
                continue
            working.add(cand["id"])
            start = max(s["start"], 390)
            out.append({"id": f"mc{i}", "employee_id": cand["id"], "day": day, "start": start, "end": s["end"],
                        "breaks": [], "segments": [{"role_id": role, "start": start, "end": s["end"]}]})
            call_list.append({"rank": len(call_list) + 1, "employee_id": cand["id"], "role_id": role,
                              "start": start, "end": s["end"], "why": "Trained and off today."})
        if kind == "changed_past":
            early = next((s for s in out if s["day"] == day and s["start"] < now and s["start"] >= 60), None)
            if early:
                early["start"] -= 60
                if early["segments"]:
                    early["segments"] = [{**early["segments"][0], "start": early["start"]}] + early["segments"][1:]
    sched = {**current, "produced_by": "baseline", "status": "feasible", "shifts": out, "metrics": None}
    return "```json\n" + json.dumps({"schedule": sched, "call_list": call_list}, separators=(",", ":")) + "\n```", "stop"


def respond(model: str, messages: list[dict]) -> tuple[str, str]:
    text = messages[-1]["content"] if len(messages) == 2 else messages[1]["content"]
    if len(messages) > 2:  # a retry after an unparseable reply: these mocks don't learn
        return "Apologies, here it is again in a table: (no JSON)", "stop"
    cfg = _tag(text, "store_config")
    if cfg is None:
        return "I could not find the store configuration.", "stop"
    current = _tag(text, "current_schedule")
    if current is not None:
        return repair(model, cfg, current, _tag(text, "callouts") or [], text)
    return weekly(model, cfg, text)
