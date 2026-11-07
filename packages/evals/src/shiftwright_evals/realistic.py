"""The realistic suite (briefs/WS5-realistic-eval.md): "manager + ChatGPT" vs "manager + Shiftwright".

Every system gets the same raw inputs: the leader's narrative, the corporate CSV exports
(`shiftwright_scenarios.exports.write_exports`) and the location. Nothing else: no law pack, no rules,
no StoreConfig. Every schedule is mapped back to the scenario's true ids and validated against the
scenario's config with the TRUE law pack.

Systems:
  chat:<model>         one plain user turn, CSVs pasted inline, asks for a CSV schedule at the end.
  shiftwright:intake   the real API in-process: create an empty store, import every CSV with the
                       proposed mapping, onboard chat with the narrative and a neutral "accept every
                       prefill" card policy, then /solve.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from shiftwright_contracts.models import Schedule, StoreConfig
from shiftwright_scenarios.exports import JOB_CODES, tm_id, write_exports

from .llm import ChatResult, LLMClient
from .suites import Case, make_case
from .systems import Output

CSV_FILES = ["roster", "training", "availability", "forecast", "history"]
CODE_TO_ROLE = {v: k for k, v in JOB_CODES.items()}
STATE_NAMES = {"TX": "Texas", "CA": "California", "IL": "Illinois", "WA": "Washington", "NY": "New York"}

LIMITATIONS = [
    "One chat turn per model and no follow-up questions; a real manager could iterate.",
    "Consumer ChatGPT/Claude/Grok apps may use browsing or code tools; this API run doesn't.",
    "The requested CSV format has no break column: breaks are read from gaps between a person's lines "
    "on the same day (gap < 30 min = paid rest, 30–60 min = unpaid meal). 10-minute rest breaks rarely "
    "appear in a schedule file, so missing rest breaks partly reflect the format.",
    "Shiftwright's intake uses a neutral manager: every card's prefill is accepted unchanged and the "
    "proposed CSV mappings are confirmed as is; nobody corrects the agent.",
    "Small sample: one seed per scenario.",
]


# --------------------------------------------------------------------------- #
# Cases and inputs
# --------------------------------------------------------------------------- #
def realistic_cases(quick: bool) -> list[Case]:
    seeds = [1] if quick else [1, 2]
    specs = [("M", "normal", "TX/austin", "retail"), ("S", "legal_trap", "CA", "retail"),
             ("M", "tight", "TX", "retail"), ("M", "normal", "IL/chicago", "food")]
    cases = []
    for size, diff, jur, sector in specs:
        for seed in seeds:
            try:
                case = make_case("realistic", size, diff, seed, jur, sector=sector)
                export_texts(case)  # food exports may not exist yet: skip the case rather than fail the run
            except Exception as exc:  # noqa: BLE001
                SKIPPED.append(f"realistic {sector} {size} {diff} {jur} s{seed}: {type(exc).__name__}: {exc}")
                continue
            cases.append(case)
    return cases


SKIPPED: list[str] = []


def export_texts(case: Case) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as d:
        write_exports(case.scenario, Path(d))
        out = {}
        for name in CSV_FILES:
            p = Path(d) / f"{name}.csv"
            if p.exists() and (name != "history" or case.scenario.history):
                out[name] = p.read_text()
        return out


def location_text(case: Case) -> tuple[str, str]:
    j = case.config.store.jurisdiction
    state = STATE_NAMES.get(j.state, j.state)
    return (j.city.title() if j.city else ""), state


def business_text(case: Case) -> str:
    sector = getattr(case.config.store, "sector", None)
    return "restaurant" if (sector == "food" or "food" in case.scenario_id) else "big-box store"


def chat_messages(case: Case, csvs: dict[str, str]) -> list[dict]:
    city, state = location_text(case)
    where = f"{city}, {state}" if city else state
    ws = case.config.store.week_start
    files = "\n\n".join(f"{name}.csv:\n```\n{text.rstrip()}\n```" for name, text in csvs.items())
    text = (f"I manage a {business_text(case)} in {where}. Here's how the store works: {case.scenario.narrative}\n"
            f"Attached are my exports from corporate. Can you make next week's schedule (week of "
            f"{ws.strftime('%A %m/%d/%Y')})? Keep me under my hours budget, make sure it's legal, and cover the "
            f"floor as well as you can.\n"
            f"At the end, give me the final schedule as CSV with columns `TM_ID,Date,Start,End,Job` so I can load it.\n"
            f"If you have to assume something, just say what you assumed.\n\n{files}\n")
    return [{"role": "user", "content": text}]


RETRY = ("I couldn't load that. Please give me just the final schedule as CSV with columns "
         "TM_ID,Date,Start,End,Job.")


# --------------------------------------------------------------------------- #
# Mapping a CSV schedule back to true ids
# --------------------------------------------------------------------------- #
TIME = re.compile(r"^\s*(\d{1,2})(?::?(\d{2}))?\s*([ap])\.?m?\.?\s*$", re.I)
TIME24 = re.compile(r"^\s*(\d{1,2}):?(\d{2})\s*$")


def parse_time(s: str) -> int | None:
    s = (s or "").strip()
    m = TIME.match(s)
    if m:
        h, mm = int(m.group(1)) % 12, int(m.group(2) or 0)
        return (h + (12 if m.group(3).lower() == "p" else 0)) * 60 + mm
    m = TIME24.match(s)
    if m and int(m.group(1)) <= 24 and int(m.group(2)) < 60:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def parse_date(s: str, week_start: date) -> int | None:
    s = (s or "").strip()
    for pat, fn in [(r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
                    (r"(\d{1,2})/(\d{1,2})/(\d{2,4})", lambda m: date(int(m[3]) + (2000 if len(m[3]) == 2 else 0),
                                                                  int(m[1]), int(m[2]))),
                    (r"(\d{1,2})/(\d{1,2})", lambda m: date(week_start.year, int(m[1]), int(m[2])))]:
        m = re.search(pat, s)
        if m:
            try:
                return (fn(m) - week_start).days
            except ValueError:
                return None
    return None


def true_employee_id(raw: str, cfg: StoreConfig) -> str:
    """TM_ID (or our internal id, or a name) -> scenario employee id; unknown stays as given (-> unknown_entity)."""
    raw = (raw or "").strip()
    by_tm = {tm_id(e.id): e.id for e in cfg.employees}
    if raw in by_tm:
        return by_tm[raw]
    digits = re.sub(r"\D", "", raw)
    if digits in by_tm:
        return by_tm[digits]
    by_name = {e.name.lower(): e.id for e in cfg.employees}
    return by_name.get(raw.lower(), raw or "unknown")


def true_role_id(raw: str, cfg: StoreConfig) -> str:
    raw = (raw or "").strip()
    if raw.upper() in CODE_TO_ROLE:
        return CODE_TO_ROLE[raw.upper()]
    ids = {r.id for r in cfg.roles}
    if raw.lower() in ids:
        return raw.lower()
    by_name = {r.name.lower(): r.id for r in cfg.roles}
    return by_name.get(raw.lower(), raw or "unknown")


def find_schedule_csv(text: str) -> str | None:
    """The last block of lines whose header has TM_ID and Date (fenced or not)."""
    blocks = re.findall(r"```(?:csv)?\s*\n(.*?)```", text or "", re.S)
    blocks = [b for b in blocks if re.search(r"TM_ID\s*,", b, re.I)]
    if blocks:
        return blocks[-1]
    lines = (text or "").splitlines()
    start = max((i for i, l in enumerate(lines) if re.match(r"\s*TM_ID\s*,\s*Date", l, re.I)), default=None)
    if start is None:
        return None
    out = []
    for l in lines[start:]:
        if not l.strip() or "," not in l:
            break
        out.append(l)
    return "\n".join(out)


def csv_to_schedule(text: str, cfg: StoreConfig, produced_by: str) -> tuple[dict | None, dict]:
    """Model reply -> Schedule dict in the scenario's true ids. Returns (None, info) if no CSV."""
    info = {"rows": 0, "bad_rows": [], "assumptions": count_assumptions(text)}
    block = find_schedule_csv(text)
    if block is None:
        return None, info
    rows = list(csv.reader(io.StringIO(block.strip())))
    header = [h.strip().lower() for h in rows[0]]
    col = {name: header.index(name) for name in ("tm_id", "date", "start", "end", "job") if name in header}
    if len(col) < 5:
        info["bad_rows"].append(f"header {rows[0]!r} lacks TM_ID,Date,Start,End,Job")
        return None, info
    lines = []
    ws = cfg.store.week_start
    for i, r in enumerate(rows[1:], 1):
        if not any(x.strip() for x in r):
            continue
        info["rows"] += 1
        try:
            emp, day = true_employee_id(r[col["tm_id"]], cfg), parse_date(r[col["date"]], ws)
            start, end = parse_time(r[col["start"]]), parse_time(r[col["end"]])
            role = true_role_id(r[col["job"]], cfg)
        except IndexError:
            info["bad_rows"].append(f"row {i}: {r!r}")
            continue
        if day is None or start is None or end is None:
            info["bad_rows"].append(f"row {i}: {r!r}")
            continue
        if end <= start:
            end += 1440
        lines.append((emp, day, start, end, role))
    shifts = []
    lines.sort(key=lambda x: (x[0], x[1], x[2]))
    for emp, day, start, end, role in lines:
        prev = shifts[-1] if shifts else None
        gap = start - prev["end"] if prev and prev["employee_id"] == emp and prev["day"] == day else None
        if gap is not None and 0 <= gap <= 60:
            if gap > 0:  # a break between two lines of the same shift
                prev["breaks"].append({"start": prev["end"], "end": start, "kind": "meal" if gap >= 30 else "rest",
                                       "paid": gap < 30})
            prev["segments"].append({"role_id": role, "start": start, "end": end})
            prev["end"] = end
            continue
        shifts.append({"id": f"c{len(shifts) + 1}", "employee_id": emp, "day": day, "start": start, "end": end,
                       "breaks": [], "segments": [{"role_id": role, "start": start, "end": end}]})
    for s in shifts:  # adjacent same-role segments merge so segments tile cleanly
        merged = []
        for g in s["segments"]:
            if merged and merged[-1]["role_id"] == g["role_id"] and merged[-1]["end"] == g["start"]:
                merged[-1]["end"] = g["end"]
            else:
                merged.append(g)
        s["segments"] = merged
    sched = {"store_id": cfg.store.id, "week_start": str(ws), "config_version": cfg.config_version,
             "produced_by": produced_by, "status": "feasible", "shifts": shifts}
    return sched, info


def count_assumptions(text: str) -> int:
    """Lines that state an assumption (heuristic: the line mentions 'assum'; a heading counts its bullets)."""
    lines = (text or "").splitlines()
    n, in_section = 0, False
    for l in lines:
        low = l.lower()
        if "assum" in low and len(l.strip()) < 60 and not l.strip().startswith(("-", "*", "•")):
            in_section = True  # a heading like "Assumptions:"
            continue
        if in_section and re.match(r"\s*([-*•]|\d+[.)])\s+", l):
            n += 1
            continue
        if in_section and l.strip() == "":
            continue
        in_section = False
        if "assum" in low:
            n += 1
    return n


# --------------------------------------------------------------------------- #
# chat:<model>
# --------------------------------------------------------------------------- #
class ChatBaseline:
    realistic = True

    def __init__(self, model: str, client: LLMClient, mock: bool = False):
        self.model = model
        self.client = client
        self.mock = mock
        self.name = f"chat:{model}"
        self.available = True
        self.unavailable_reason = None

    async def run_realistic(self, case: Case) -> Output:
        from .prompts import render

        csvs = export_texts(case)
        messages = chat_messages(case, csvs)
        attempts, raws, latency, res, sched, info = [], [], 0.0, None, None, {}
        for attempt in range(2):  # one retry if no loadable CSV
            res = await self.client.complete(self.model, messages)
            latency += res.latency_s
            raws.append(res.text)
            attempts.append({"finish_reason": res.finish_reason, "latency_s": res.latency_s, "chars": len(res.text),
                             "usage": res.usage, "error": res.error})
            if res.error:
                break
            sched, info = csv_to_schedule(res.text, case.config, self.name)
            if sched is not None or res.finish_reason == "length" or attempt == 1:
                break
            messages = messages + [{"role": "assistant", "content": res.text}, {"role": "user", "content": RETRY}]
        out = Output(render(messages), raw_text=raws[-1], latency_s=round(latency, 2), attempts=attempts)
        if len(raws) > 1:
            out.extra_files["raw_output.attempt1.txt"] = raws[0]
        out.extra_files["mapping.json"] = json.dumps(info, indent=1)
        if res.error:
            out.outcome, out.note = "error", res.error
            return out
        if res.finish_reason == "length":
            out.outcome = "truncated"
        elif sched is None:
            out.outcome = "unparseable"
        out.schedule_input = sched if sched is not None else res.text
        return out


# --------------------------------------------------------------------------- #
# shiftwright:intake (the real API, in-process)
# --------------------------------------------------------------------------- #
ACCEPT_KEY = "__accept_prefill__"
CARD_LOGS: dict[str, list] = {}
FOLLOW_UP = "Please keep going and finish setting up the store from what I told you."
MAX_TURNS = 4


def accept_prefill(card_type: str, props: dict) -> dict:
    """A neutral manager: accept what the card proposes, unchanged. Never reads the scenario's answers."""
    if card_type in ("store_basics", "payroll"):
        return {k: v for k, v in props.items() if k not in ("id", "approvals")}
    if card_type == "roles":
        return {"departments": props.get("departments", []), "roles": props.get("roles", [])}
    if card_type == "training_matrix":
        return {e["id"]: e.get("trained_role_ids", []) for e in props.get("employees", [])}
    if card_type == "coverage_grid":
        return {"prefill": props.get("prefill") or {}}
    if card_type == "department_staffing":
        return {"staffing": props.get("suggested") or {}}
    if card_type == "events":
        return {"events": props.get("events", [])}
    if card_type == "csv_import":
        return {"committed": False, "rows": 0, "note": "already imported"}
    if card_type == "propose_rule":
        c = props.get("constraint") or {}
        res = {"decision": c.get("strength", "soft")}
        if res["decision"] == "soft" and c.get("weight_dollars"):
            res["weight_dollars"] = c["weight_dollars"]
        return res
    if card_type in ("tradeoff", "conflict_menu"):
        opts = props.get("options") or []
        return {"option_id": opts[0]["id"]} if opts else {"cancelled": True}
    if card_type == "employee_availability":
        return {"confirmed": props.get("parsed") or []}
    return {"cancelled": True}


def _patch_waiter(main_mod) -> None:
    """Make `?auto_cards=scripted` with card_script {ACCEPT_KEY: []} use the accept-prefill policy.
    Pending WS6 support for this mode (contracts/requests/ws5-accept-prefill.md)."""
    if getattr(main_mod, "_ws5_patched", False):
        return
    original = main_mod.scripted_waiter

    def waiter(script):
        if ACCEPT_KEY not in (script or {}):
            return original(script)
        token = ((script[ACCEPT_KEY] or [{}])[0] or {}).get("token", "default")
        log = CARD_LOGS.setdefault(token, [])

        async def wait(card_id, card_type, props):
            result = accept_prefill(card_type, props)
            log.append({"card_type": card_type, "result_keys": sorted(result)})
            return result
        return wait
    main_mod.scripted_waiter = waiter
    main_mod._ws5_patched = True


def map_built_schedule(sched: dict, built: dict, cfg: StoreConfig) -> dict:
    """Shiftwright's schedule uses the ids its import created (TM_ID employees, job-code roles): map them
    to the scenario's true ids the same way a baseline's CSV is mapped."""
    out = json.loads(json.dumps(sched))
    out["store_id"], out["week_start"] = cfg.store.id, str(cfg.store.week_start)
    out["config_version"] = cfg.config_version
    for s in out.get("shifts", []):
        s["employee_id"] = true_employee_id(s["employee_id"], cfg)
        for g in s.get("segments", []):
            g["role_id"] = true_role_id(g["role_id"], cfg)
    out["metrics"] = None  # metrics were computed on Shiftwright's own config; the validator recomputes
    out["gaps"], out["soft_violations"] = [], []
    return out


def intake_recall(case: Case, built: dict) -> dict:
    """Fraction of the narrative's facts present in the config the agent built (Shiftwright only)."""
    cfg = case.config
    emp = lambda eid: tm_id(eid)  # noqa: E731 - built ids are TM_IDs
    role = lambda rid: JOB_CODES.get(rid, rid).lower()  # noqa: E731
    cons = [c for c in built.get("constraints", []) if c.get("status") == "confirmed"]
    hours = {h["day"]: (h["open"], h["close"]) for h in built.get("store", {}).get("hours", [])}
    checks = []
    for f in case.scenario.expected.get("narrative_facts", []):
        k, ok = f["kind"], None
        if k == "store_hours":
            ok = all(hours.get(d) == (f["open"], f["close"]) for d in f["days"])
        elif k == "store_hours_by_day":
            ok = all(hours.get(int(d)) == tuple(v) for d, v in f["hours"].items())
        elif k == "budget_hours_cap":
            got = built.get("budget", {}).get("weekly_hours_cap") or 0
            ok = abs(got - f["value"]) <= max(1.0, 0.01 * f["value"])
        elif k == "overtime_allowed":
            ok = built.get("budget", {}).get("overtime_allowed") == f["value"]
        elif k == "max_shifts_per_day":
            ok = built.get("store", {}).get("max_shifts_per_day") == f["value"]
        elif k in ("truck", "event"):
            days = f.get("days") or [f.get("day")]
            evs = built.get("events", [])
            ok = all(any(e.get("day") == d and e.get("start", 0) < f["end"] and f["start"] < e.get("end", 0)
                         for e in evs) for d in days)
        elif k == "always_staffed":
            ok = any(c["kind"] == "always_staffed" and c.get("params", {}).get("role_id") == role(f["role_id"]) for c in cons)
        elif k in ("min_shift_length", "max_shift_length", "min_rest_between_shifts"):
            ok = any(c["kind"] == k and c.get("params", {}).get("minutes") == f["minutes"] for c in cons)
        elif k == "not_together":
            want = {emp(x) for x in f["employee_ids"]}
            ok = any(c["kind"] == "not_together" and set(c.get("params", {}).get("employee_ids", [])) == want for c in cons)
        elif k == "preferred_role":
            ok = any(c["kind"] == "preferred_role" and c.get("params", {}).get("employee_id") == emp(f["employee_id"])
                     and c.get("params", {}).get("role_id") == role(f["role_id"]) for c in cons)
        elif k == "availability":
            by_id = {e["id"]: e for e in built.get("employees", [])}

            def blocked(e):
                av = (by_id.get(emp(e)) or {}).get("availability", [])
                return all(any(a.get("kind") == f.get("availability_kind", "unavailable") and a.get("weekday") == wd
                               and a.get("start", 0) <= f["start"] and a.get("end", 0) >= f["end"] for a in av)
                           for wd in f["weekdays"])
            ok = all(blocked(e) for e in f["employee_ids"])
        elif k == "unmodeled":
            name = next((e.name for e in cfg.employees if e.id == f.get("employee_id")), "")
            ok = any(name.split()[0].lower() in (n.get("text", "") + n.get("reason", "")).lower()
                     for n in built.get("unmodeled", [])) if name else None
        checks.append({"kind": k, "present": ok})
    scored = [c for c in checks if c["present"] is not None]
    contra = case.scenario.expected.get("narrative_contradictions") or []
    return {"facts": checks, "checked": len(scored), "present": sum(1 for c in scored if c["present"]),
            "recall": round(sum(1 for c in scored if c["present"]) / len(scored), 3) if scored else None,
            "contradictions_expected": len(contra), "contradiction_flagged": None if not contra else "not scored"}


class ShiftwrightIntake:
    realistic = True
    name = "shiftwright:intake"

    def __init__(self, agent: str = "fake", time_limit_s: float = 120, workers: int = 1):
        """agent: "fake" (the API's FakeLLM, no key: the narrative is not understood) or "real"
        (the API's OpenRouter agent, AGENT_MODEL)."""
        self.agent = agent
        self.time_limit_s = time_limit_s
        self.sem = asyncio.Semaphore(workers)
        try:
            import shiftwright_api.main  # noqa: F401
            self.available, self.unavailable_reason = True, None
        except Exception as exc:  # noqa: BLE001
            self.available, self.unavailable_reason = False, f"shiftwright_api not importable ({type(exc).__name__})"

    async def run_realistic(self, case: Case) -> Output:
        steps_doc = (f"shiftwright:intake ({self.agent} agent)\n1. POST /api/stores template=empty\n"
                     "2. POST /import/{kind} + /commit with the proposed mapping, for each CSV\n"
                     "3. POST /chat?auto_cards=scripted mode=onboard, first message = the narrative below; "
                     "every card's prefill accepted unchanged\n"
                     f"4. POST /solve time_limit_s={self.time_limit_s:g}\n\n--- narrative ---\n{case.scenario.narrative}\n")
        if not self.available:
            return Output(steps_doc, outcome="unavailable", note=self.unavailable_reason)
        async with self.sem:
            t0 = time.perf_counter()
            try:
                log = await asyncio.to_thread(self._run_sync, case)
            except Exception as exc:  # noqa: BLE001 - a product failure is an outcome
                return Output(steps_doc, raw_text=f"{type(exc).__name__}: {exc}", outcome="error",
                              note=f"intake failed: {type(exc).__name__}: {exc}"[:300],
                              latency_s=round(time.perf_counter() - t0, 2))
            latency = round(time.perf_counter() - t0, 2)
        out = Output(steps_doc, raw_text=json.dumps(log["solve"], indent=1)[:2_000_000], latency_s=latency)
        out.extra_files["built_config.json"] = json.dumps(log["built"], indent=1)
        out.extra_files["intake_log.json"] = json.dumps({k: log[k] for k in ("imports", "turns", "cards", "readiness")},
                                                        indent=1, default=str)
        out.extra_files["intake_recall.json"] = json.dumps(intake_recall(case, log["built"]), indent=1)
        sched = (log["solve"] or {}).get("schedule")
        if not sched:
            out.outcome, out.note = "error", f"/solve failed: {str(log.get('solve_error'))[:300]}"
            out.schedule_input = None
            return out
        out.schedule_input = map_built_schedule(sched, log["built"], case.config)
        return out

    def _run_sync(self, case: Case) -> dict:
        import dataclasses

        from fastapi.testclient import TestClient
        import shiftwright_api.main as main_mod
        from shiftwright_api.agent.llm import FakeLLM, OpenRouterClient, call, say
        from shiftwright_api.settings import Settings

        _patch_waiter(main_mod)
        csvs = export_texts(case)
        with tempfile.TemporaryDirectory() as tmp:
            settings = dataclasses.replace(Settings.from_env(), database_url=f"sqlite:///{tmp}/sw.db",
                                           demo_key="", messenger="mock")
            if self.agent == "real":
                llm = OpenRouterClient(settings.openrouter_api_key, settings.agent_model)
                helper = llm
            else:
                settings = dataclasses.replace(settings, openrouter_api_key="")
                # A scripted stand-in that never reads the narrative: it opens the basics and payroll cards
                # (accepted unchanged) so the card path runs end to end without a key.
                llm = FakeLLM([call("ask_store_basics"), call("ask_payroll"),
                               say("(mock agent: no model configured, narrative not read)")])
                helper = None
            app = main_mod.create_app(settings, llm=llm, helper_llm=helper)
            log: dict = {"imports": [], "turns": [], "cards": [], "solve": None}
            with TestClient(app) as c:
                j = case.config.store.jurisdiction
                r = c.post("/api/stores", json={"template": "empty", "name": case.config.store.name,
                                                "jurisdiction": j.model_dump()})
                r.raise_for_status()
                sid = r.json()["store"]["id"]
                for kind, text in csvs.items():
                    pv = c.post(f"/api/stores/{sid}/import/{kind}",
                                files={"file": (f"{kind}.csv", text.encode(), "text/csv")})
                    entry = {"kind": kind, "preview_status": pv.status_code}
                    if pv.status_code == 200:
                        p = pv.json()
                        entry.update(proposed_mapping=p["proposed_mapping"], unmapped_required=p["unmapped_required"])
                        cm = c.post(f"/api/stores/{sid}/import/{kind}/commit", json={"mapping": p["proposed_mapping"]})
                        entry.update(commit_status=cm.status_code,
                                     commit_detail=None if cm.status_code == 200 else cm.text[:300],
                                     warnings=c.get(f"/api/stores/{sid}/import/{kind}/warnings").json().get("warnings"))
                    log["imports"].append(entry)
                messages = [case.scenario.narrative]
                for turn in range(MAX_TURNS):
                    token = f"{case.scenario_id}|{turn}|{id(app)}"
                    card_log = CARD_LOGS.setdefault(token, [])
                    body = {"mode": "onboard", "messages": [{"role": "user", "content": messages[-1]}],
                            "card_script": {ACCEPT_KEY: [{"token": token}]}}
                    events = []
                    with c.stream("POST", f"/api/stores/{sid}/chat?auto_cards=scripted", json=body) as resp:
                        for line in resp.iter_lines():
                            if line.startswith("event:"):
                                events.append(line[6:].strip())
                    log["turns"].append({"turn": turn, "status": resp.status_code, "events": dict(_count(events))})
                    log["cards"] += CARD_LOGS.pop(token, card_log)
                    ready = c.get(f"/api/stores/{sid}/readiness").json()
                    log["readiness"] = ready
                    if ready.get("ready") or self.agent != "real":
                        break
                    messages.append(FOLLOW_UP)
                log["built"] = c.get(f"/api/stores/{sid}/config").json()
                sv = c.post(f"/api/stores/{sid}/solve", json={"time_limit_s": self.time_limit_s})
                if sv.status_code == 200:
                    log["solve"] = sv.json()
                else:
                    log["solve_error"] = f"HTTP {sv.status_code}: {sv.text[:500]}"
        return log


def _count(xs):
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out
