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


# Quick weekly stores in suite order. Mock assignment is keyed on the store's identity (never the prompt
# text, which changes with every contract/fixture tweak): on these six stores each mock walks its list
# once, so every failure kind appears at least once in --quick.
QUICK_ORDER = ["s-easy", "s-tight", "s-legal_trap", "m-easy", "m-tight", "m-legal_trap"]
MODEL_OFFSET = {"mock-a": 0, "mock-b": 1}
CHAT_ORDER = ["Austin, Texas", "California", "Texas", "Chicago, Illinois"]
CHAT_OFFSET = {"mock-a": 0, "mock-b": 2}  # the 3 retail stores x 2 mocks cover all 5 chat kinds


def _pick(model: str, store_id: str, kinds: list[str], suite: str = "weekly") -> str:
    m = re.fullmatch(r"gen-([sml])-(.+)-(\d+)", store_id or "")
    if suite == "weekly" and m:
        if m.group(2) == "infeasible":
            # Mocks never detect infeasibility; mock-a always returns a confident "feasible" schedule.
            return "sloppy" if model == "mock-a" else kinds[int(m.group(3)) % len(kinds)]
        key = f"{m.group(1)}-{m.group(2)}"
        if key in QUICK_ORDER:
            i = QUICK_ORDER.index(key) + int(m.group(3)) - 1 + MODEL_OFFSET.get(model, 0)
            return kinds[i % len(kinds)]
    if suite == "chat" and store_id in CHAT_ORDER:  # realistic quick stores, keyed on the stated location
        return kinds[(CHAT_ORDER.index(store_id) + CHAT_OFFSET.get(model, 0)) % len(kinds)]
    h = int(hashlib.sha256(f"{model}|{suite}|{store_id}".encode()).hexdigest(), 16)
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
    kind = _pick(model, cfg["store"]["id"], WEEKLY_KINDS.get(model, WEEKLY_KINDS["mock-a"]))
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
    kind = _pick(model, cfg["store"]["id"], REPAIR_KINDS, suite="repair")
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


CHAT_KINDS = ["careful", "wrong_ids", "no_breaks", "over_budget", "unparseable"]


def _csv_block(text: str, name: str) -> list[dict]:
    import csv as _csv
    import io as _io
    m = re.search(rf"{name}\.csv:\n```\n(.*?)\n```", text, re.S)
    return list(_csv.DictReader(_io.StringIO(m.group(1)))) if m else []


def _t12(m: int) -> str:
    m %= 1440
    h, mm = divmod(m, 60)
    return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


def _parse12(s: str) -> int:
    m = re.match(r"(\d{1,2}):(\d{2}) ([AP])M", s.strip())
    return (int(m[1]) % 12 + (12 if m[3] == "P" else 0)) * 60 + int(m[2])


def chat(model: str, text: str) -> tuple[str, str]:
    """A manager's chat reply: prose, stated assumptions, then a CSV built greedily from forecast.csv and
    training.csv (availability ignored), with one failure kind injected."""
    store = re.search(r"in ([^.]+)\. Here's", text)
    kind = _pick(model, store.group(1) if store else text[:80], CHAT_KINDS, suite="chat")
    if kind == "unparseable":
        return ("Here's a draft plan: openers come in at 6, mid shift 11-7, closers 2-10. Rotate weekends "
                "fairly and keep minors off the forklift. Let me know if you want it as a file!"), "stop"
    trained: dict[str, list[str]] = {}
    for r in _csv_block(text, "training"):
        trained.setdefault(r["Job Code"], []).append(r["TM_ID"])
    hours: dict[str, float] = {}
    busy: dict[tuple[str, str], list[tuple[int, int]]] = {}
    rows = []
    for f in _csv_block(text, "forecast"):
        start, end = _parse12(f["Start Time"]), _parse12(f["End Time"])
        if end <= start:
            end += 1440
        t = start
        while t < end:
            e2 = min(end, t + 480)
            pool = sorted(trained.get(f["Job Code"], []), key=lambda x: (hours.get(x, 0), x))
            placed = 0
            for tm in pool:
                if placed >= int(f["Req HC"]):
                    break
                spans = busy.setdefault((tm, f["Date"]), [])
                if any(a < e2 and t < b for a, b in spans):
                    continue
                spans.append((t, e2))
                hours[tm] = hours.get(tm, 0) + (e2 - t) / 60
                rows.append([tm, f["Date"], t, e2, f["Job Code"]])
                placed += 1
            t = e2
    out = []
    for tm, d, a, b, job in rows:
        if kind == "wrong_ids":
            tm = tm[:-1] + str((int(tm[-1]) + 5) % 10) if tm else tm
        if kind in ("careful", "over_budget") and b - a > 360:
            mid = a + (b - a) // 2 // 30 * 30
            out += [[tm, d, _t12(a), _t12(mid), job], [tm, d, _t12(mid + 30), _t12(b), job]]  # 30-min lunch gap
        else:
            out.append([tm, d, _t12(a), _t12(b), job])
        if kind == "over_budget":
            out.append([tm, d, _t12(b), _t12(min(b + 120, 1439)), job])
    lines = ["TM_ID,Date,Start,End,Job"] + [",".join(map(str, r)) for r in out]
    return ("Here's next week's schedule. Assumptions:\n- Shifts are at most 8 hours.\n- Everyone in "
            "training.csv can work those jobs any day.\n\n```csv\n" + "\n".join(lines) + "\n```\n"), "stop"


def respond(model: str, messages: list[dict]) -> tuple[str, str]:
    text = next(m["content"] for m in messages if m["role"] == "user")
    retry = any(m["role"] == "assistant" for m in messages)
    if text.startswith("I manage a "):
        if retry:
            return "Sorry, I can't produce a file here.", "stop"
        return chat(model, text)
    if retry:  # a retry after an unparseable reply: these mocks don't learn
        return "Apologies, here it is again in a table: (no JSON)", "stop"
    cfg = _tag(text, "store_config")
    if cfg is None:
        return "I could not find the store configuration.", "stop"
    current = _tag(text, "current_schedule")
    if current is not None:
        return repair(model, cfg, current, _tag(text, "callouts") or [], text)
    return weekly(model, cfg, text)
