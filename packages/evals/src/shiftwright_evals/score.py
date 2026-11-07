"""Score a run folder. Every number comes from the files on disk: validation.json (the validator's
report), schedule.json (what the system returned, as parsed), run.json (outcome, latency) and
_inputs/ (config, expected, call-out inputs). Nothing is computed from in-memory state, so anyone
can recount the report from the folder.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

from shiftwright_contracts.models import CallOut, Schedule, StoreConfig
from shiftwright_validator import recompute_metrics

SCORED = ("ok", "unparseable", "truncated")  # outcomes that count toward rates (errors/unavailable don't)
BUDGET_CODES = {"budget_hours", "budget_dollars"}


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def _minutes(schedule: Schedule, employee_id: str, day: int, before: int | None) -> set[tuple[int, str]]:
    out = set()
    for s in schedule.shifts:
        if s.employee_id != employee_id or s.day != day:
            continue
        for g in s.segments:
            for m in range(g.start, g.end if before is None else min(g.end, before)):
                out.add((m, g.role_id))
    return out


def drop_callouts(base: Schedule, callouts: list[CallOut]) -> Schedule:
    """The schedule as it stands right after the call-outs: their remaining time on that day removed."""
    gone = {(c.employee_id, c.day): c.reported_at for c in callouts}
    shifts = []
    for s in base.shifts:
        cut = gone.get((s.employee_id, s.day))
        if cut is None or s.end <= cut:
            shifts.append(s)
        elif s.start < cut:
            segs = [g.model_copy(update={"end": min(g.end, cut)}) for g in s.segments if g.start < cut]
            brks = [b for b in s.breaks if b.end <= cut]
            shifts.append(s.model_copy(update={"end": cut, "segments": segs, "breaks": brks}))
    return base.model_copy(update={"shifts": shifts, "metrics": None})


def repair_metrics(cfg: StoreConfig, base: Schedule, callouts: list[CallOut], day: int, now: int,
                   revised: Schedule | None, call_list) -> dict:
    after_callouts = drop_callouts(base, callouts)
    out = {
        "coverage_original": round(recompute_metrics(cfg, base).coverage_pct, 1),
        "coverage_before": round(recompute_metrics(cfg, after_callouts).coverage_pct, 1),
        "changes_before_now": None, "callouts_still_working": None,
        "call_list_size": len(call_list) if isinstance(call_list, list) else None,
        "call_list_unknown_ids": None,
    }
    roster = {e.id for e in cfg.employees}
    if isinstance(call_list, list):
        out["call_list_unknown_ids"] = sum(1 for c in call_list
                                           if not isinstance(c, dict) or c.get("employee_id") not in roster)
    if revised is None:
        return out
    called = {c.employee_id for c in callouts}
    changed = set()
    for eid in roster | {s.employee_id for s in revised.shifts}:
        if eid in called:
            continue
        for d in range(day + 1):
            cut = now if d == day else None
            if _minutes(base, eid, d, cut) != _minutes(revised, eid, d, cut):
                changed.add(eid)
                break
    out["changes_before_now"] = len(changed)
    out["callouts_still_working"] = sum(
        1 for c in callouts
        if any(m >= c.reported_at for m, _ in _minutes(revised, c.employee_id, c.day, None)))
    return out


def score_run(run_dir: Path, folder: Path, inputs_cache: dict) -> dict:
    meta = _load(folder / "run.json")
    sid = meta["scenario"]
    if sid not in inputs_cache:
        inp = run_dir / "_inputs" / sid
        inputs_cache[sid] = {"config": StoreConfig.model_validate_json((inp / "config.json").read_text()),
                             "expected": _load(inp / "expected.json") or {}, "dir": inp}
    cfg = inputs_cache[sid]["config"]
    val = _load(folder / "validation.json")
    sched_raw = _load(folder / "schedule.json")
    schedule = Schedule.model_validate(sched_raw) if sched_raw else None
    row = {
        "key": f"{meta['system']}|{sid}".replace(":", "_").replace("/", "_").replace("|", "--"),
        "system": meta["system"], "suite": meta["suite"], "scenario": sid, "size": meta["size"],
        "difficulty": meta["difficulty"], "seed": meta["seed"], "outcome": meta["outcome"],
        "latency_s": meta["latency_s"], "note": meta.get("note", ""),
        "path": folder.relative_to(run_dir).as_posix(),
        "expected_infeasible": meta["expected_infeasible"],
        "expected_suspect": meta.get("expected_suspect"),
        "reused_from": meta.get("reused_from"),
        "cost_usd": round(sum(float((a.get("usage") or {}).get("cost") or 0) for a in meta.get("attempts", [])), 4),
    }
    if val is None:
        return row
    hard = [v for v in val["violations"] if v["severity"] == "hard"]
    m = val["recomputed_metrics"]
    by_code = dict(Counter(v["code"] for v in hard))
    said_infeasible = bool(schedule and (schedule.status == "infeasible" or schedule.infeasibility is not None))
    named = None
    if said_infeasible and schedule.infeasibility:
        inf = schedule.infeasibility
        ids = set(inf.conflicting_constraint_ids + inf.conflicting_law_rule_ids + inf.conflicting_other)
        named = bool(ids & set(meta.get("expected_conflicting_ids") or []))
    row.update({
        "parsed": schedule is not None,
        "hard_count": len(hard), "passed": len(hard) == 0, "by_code": by_code,
        "status": schedule.status if schedule else None,
        "shifts": len(schedule.shifts) if schedule else 0,
        "coverage_pct": round(m["coverage_pct"], 1),
        "wage_cost": round(m["total_wage_cost"], 2),
        "objective": round(m["objective_dollars"], 2),
        "hours_used": round(m["budget_hours_used"], 1),
        "hours_cap": round(m["budget_hours_cap"], 1),
        "budget_ok": schedule is not None and not (BUDGET_CODES & set(by_code)),
        "said_infeasible": said_infeasible, "named_conflict": named,
    })
    if meta["suite"] in ("weekly", "honesty") and meta["outcome"] in SCORED:
        # status "error" (e.g. the solver found nothing in time) is an answer of neither kind.
        answered = schedule is not None and schedule.status != "error"
        if row["expected_infeasible"]:
            row["honesty"] = "TP" if said_infeasible else ("FN" if answered else "no_answer")
        else:
            row["honesty"] = "FP" if said_infeasible else ("TN" if answered else "no_answer")
            if said_infeasible and row["expected_suspect"]:
                row["honesty"] = "suspect"  # the scenario's expected flag is known to be wrong
    if meta["suite"] == "repair":
        inp = inputs_cache[sid]["dir"]
        base = Schedule.model_validate_json((inp / "base_schedule.json").read_text())
        callouts = [CallOut.model_validate(c) for c in _load(inp / "callouts.json")]
        info = _load(inp / "repair.json")
        rm = repair_metrics(cfg, base, callouts, info["day"], info["now"], schedule, _load(folder / "call_list.json"))
        rm["coverage_after"] = row["coverage_pct"] if schedule else None
        rm["base_source"] = info["base_source"]
        row.update(rm)
    return row


def collect(run_dir: Path) -> list[dict]:
    cache: dict = {}
    rows = [score_run(run_dir, f.parent, cache) for f in sorted(run_dir.glob("*/*/run.json"))]
    # Cost vs Shiftwright's objective: only against an engine schedule that passed the validator.
    sw = {r["scenario"]: r for r in rows if r["system"] == "shiftwright" and r.get("passed")}
    for r in rows:
        ref = sw.get(r["scenario"])
        r["cost_vs_sw"] = (round(r["objective"] / ref["objective"], 3)
                           if ref and r.get("parsed") and ref["objective"] > 0 else None)
    return rows


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def aggregate(rows: list[dict], systems: list[str]) -> dict:
    agg = {}
    for name in systems:
        mine = [r for r in rows if r["system"] == name]
        per_suite = {}
        for suite in ("weekly", "honesty", "repair"):
            rs = [r for r in mine if r["suite"] == suite]
            scored = [r for r in rs if r["outcome"] in SCORED]
            parsed = [r for r in scored if r.get("parsed")]
            codes = Counter()
            for r in scored:
                codes.update(r.get("by_code", {}))
            per_suite[suite] = {
                "runs": len(rs), "scored": len(scored),
                "unavailable": sum(r["outcome"] == "unavailable" for r in rs),
                "errors": sum(r["outcome"] == "error" for r in rs),
                "unparseable": sum(r["outcome"] == "unparseable" for r in rs),
                "truncated": sum(r["outcome"] == "truncated" for r in rs),
                "passed": sum(1 for r in scored if r.get("passed")),
                "pass_rate": round(100 * sum(1 for r in scored if r.get("passed")) / len(scored), 1) if scored else None,
                "hard_total": sum(r.get("hard_count", 0) for r in scored),
                "hard_by_code": dict(sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))),
                "median_coverage": _median([r["coverage_pct"] for r in parsed]),
                "median_legal_coverage": _median([r["coverage_pct"] for r in parsed if r.get("passed")]),
                "budget_ok": sum(1 for r in parsed if r.get("budget_ok")),
                "parsed": len(parsed),
                "median_cost_vs_sw": _median([r.get("cost_vs_sw") for r in parsed if r.get("passed")]),
                "median_latency_s": _median([r["latency_s"] for r in scored]),
                "total_latency_s": round(sum(r["latency_s"] or 0 for r in scored), 1),
            }
        per_suite["cost_usd"] = round(sum(r.get("cost_usd") or 0 for r in mine), 2)
        hon = Counter(r["honesty"] for r in mine if r.get("honesty") and r["suite"] == "honesty")
        per_suite["honesty_counts"] = {k: hon.get(k, 0) for k in ("TP", "FN", "FP", "TN", "no_answer")}
        per_suite["weekly_false_infeasible"] = sum(1 for r in mine if r["suite"] == "weekly" and r.get("honesty") == "FP")
        per_suite["named_conflict"] = sum(1 for r in mine if r.get("honesty") == "TP" and r.get("named_conflict"))
        agg[name] = per_suite
    return agg


def worked_example(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """(baseline run, Shiftwright run on the same scenario). Prefers scenarios where Shiftwright passed,
    then a baseline that put a minor on a prohibited role (the demo's law catch), then the most distinct
    violation codes. Deterministic."""
    sw = {r["scenario"]: r for r in rows if r["system"] == "shiftwright" and r["suite"] == "weekly"}
    cands = [r for r in rows if r["system"].startswith("baseline:") and r["suite"] == "weekly"
             and r.get("parsed") and r.get("hard_count")]
    if not cands:
        return None, None

    def rank(r):
        ref = sw.get(r["scenario"])
        return (bool(ref and ref.get("passed")), "minor_prohibited_role" in r["by_code"],
                len(r["by_code"]), r["hard_count"], r["key"])

    best = max(cands, key=rank)
    return best, sw.get(best["scenario"])
