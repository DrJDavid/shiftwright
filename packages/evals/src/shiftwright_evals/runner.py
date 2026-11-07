"""Run every (system, case), validate, and write the run folders.

runs/<run_id>/
  manifest.json
  _inputs/<scenario>/{config.json, expected.json[, base_schedule.json, callouts.json, repair.json]}
  <system>/<scenario>/{prompt.txt, raw_output.txt, schedule.json, validation.json, run.json[, call_list.json]}
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from shiftwright_contracts.models import CallOut, Schedule
from shiftwright_scenarios import pick_callouts
from shiftwright_validator import parse_schedule_lenient, validate_raw

from .suites import REPAIR_NOW, Case
from .systems import Output, ShiftwrightSystem


def system_slug(name: str) -> str:
    return name.replace(":", "_").replace("/", "__")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=False, default=str) + "\n"


async def prepare_repair(case: Case, engine: ShiftwrightSystem, inputs: Path, reuse: Path | None = None) -> dict:
    """Base schedule for the call-out suite: the engine's week if available, else the scenario's most
    recent history week re-dated (a greedy schedule built by WS4; noted in the report). With `reuse`
    (a previous run's _inputs/<scenario>), its base schedule and call-outs are reused so re-scored
    baseline repairs and the engine's fix_day answer the same question."""
    cfg = case.config
    if reuse is not None and (reuse / "base_schedule.json").exists():
        base = Schedule.model_validate_json((reuse / "base_schedule.json").read_text())
        callouts = [CallOut.model_validate(c) for c in json.loads((reuse / "callouts.json").read_text())]
        info = json.loads((reuse / "repair.json").read_text())
        info["base_source"] = f"{info['base_source']} (reused from {reuse.parent.parent.name})"
        _write(inputs / "base_schedule.json", base.model_dump_json(indent=1))
        _write(inputs / "callouts.json", _dump([c.model_dump(mode="json") for c in callouts]))
        _write(inputs / "repair.json", _dump(info))
        return {"base": base, "callouts": callouts, **info}
    base: Schedule | None = None
    source = ""
    if engine.available:
        try:
            base, _ = await engine.solve(cfg)
            source = "engine solve_week"
            if not base.shifts:
                base, source = None, f"engine returned no shifts (status {base.status}); "
        except Exception as exc:  # noqa: BLE001
            source = f"engine failed ({type(exc).__name__}); "
    else:
        source = "engine unavailable; "
    if base is None:
        hist = case.scenario.history[-1]
        base = hist.model_copy(update={"week_start": cfg.store.week_start, "store_id": cfg.store.id,
                                       "config_version": cfg.config_version, "produced_by": "history-fallback"})
        source += "history week (greedy, WS4) re-dated"
    day = int(case.scenario.expected.get("callout_day", max(d.day for d in cfg.demand)))
    callouts = pick_callouts(cfg, base, day, n=3, now=REPAIR_NOW, seed=case.seed)
    info = {"day": day, "now": REPAIR_NOW, "base_source": source}
    _write(inputs / "base_schedule.json", base.model_dump_json(indent=1))
    _write(inputs / "callouts.json", _dump([c.model_dump(mode="json") for c in callouts]))
    _write(inputs / "repair.json", _dump(info))
    return {"base": base, "callouts": callouts, **info}


def config_changes(old: dict, new: dict, path: str = "") -> list[str]:
    """Paths (with list indices collapsed to [*]) whose values differ between two config dicts."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new)):
            if old.get(k) != new.get(k):
                out += config_changes(old.get(k), new.get(k), f"{path}.{k}")
        return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        out = []
        for a, b in zip(old, new):
            if a != b:
                out += config_changes(a, b, f"{path}[*]")
        return sorted(set(out))
    return [path or "."]


# A re-scored reply is only meaningful if the store it scheduled still has the same people, roles,
# demand and week. Other changes (new defaulted fields, wages, rules) are scored under the current rules.
BLOCKING_PREFIXES = (".employees", ".roles", ".demand", ".store.week_start", ".store.hours", ".store.id")


def blocking(changes: list[str], old: dict, new: dict) -> list[str]:
    out = []
    ids = lambda cfg, key: sorted(x["id"] for x in cfg.get(key, []))  # noqa: E731
    for key in ("employees", "roles"):
        if ids(old, key) != ids(new, key):
            out.append(f"{key} ids changed")
    for c in changes:
        if c.startswith((".demand", ".store.week_start", ".store.hours", ".store.id")):
            out.append(c)
    return sorted(set(out))


def write_run(folder: Path, system: str, case: Case, out: Output) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / "prompt.txt", out.prompt_text)
    _write(folder / "raw_output.txt", out.raw_text)
    for name, text in out.extra_files.items():
        _write(folder / name, text)
    if out.outcome == "unavailable":
        schedule, report = None, None
    elif out.schedule_input is None:
        schedule, report = None, validate_raw(case.config, out.raw_text or "")
    else:
        schedule, _ = parse_schedule_lenient(out.schedule_input)
        report = validate_raw(case.config, out.schedule_input)
    _write(folder / "schedule.json", schedule.model_dump_json(indent=1) if schedule else "null\n")
    _write(folder / "validation.json", report.model_dump_json(indent=1) if report else "null\n")
    if out.call_list is not None:
        _write(folder / "call_list.json", _dump(out.call_list))
    meta = {
        "reused_from": out.note if out.note.startswith("re-scored") else None,
        "system": system, "suite": case.suite, "scenario": case.scenario_id, "size": case.size,
        "difficulty": case.difficulty, "seed": case.seed, "jurisdiction": case.jurisdiction,
        "outcome": out.outcome, "latency_s": out.latency_s, "attempts": out.attempts, "note": out.note,
        "expected_infeasible": case.expected_infeasible,
        "expected_suspect": case.expected_suspect,
        "expected_conflicting_ids": case.scenario.expected.get("conflicting_ids", []),
    }
    _write(folder / "run.json", _dump(meta))


async def run_all(cases: list[Case], systems: list, run_dir: Path, concurrency: int = 4,
                  log=print, reuse_inputs: Path | None = None) -> None:
    sem = asyncio.Semaphore(concurrency)
    engine = next((s for s in systems if isinstance(s, ShiftwrightSystem)), None) or ShiftwrightSystem(enabled=False)
    repairs: dict[str, dict] = {}
    for case in cases:
        inputs = run_dir / "_inputs" / case.scenario_id
        _write(inputs / "config.json", case.config.model_dump_json(indent=1))
        _write(inputs / "expected.json", _dump(case.scenario.expected))
    if reuse_inputs is not None:
        for case in cases:
            old_path = reuse_inputs / case.scenario_id / "config.json"
            if not old_path.exists():
                continue
            old = json.loads(old_path.read_text())
            new = json.loads(case.config.model_dump_json())
            changes = config_changes(old, new)
            block = blocking(changes, old, new)
            _write(run_dir / "_inputs" / case.scenario_id / "config_changes.json",
                   _dump({"compared_with": str(old_path.parent.parent.parent.name), "changed": changes,
                          "blocking": block}))
            for s in systems:
                if getattr(s, "replay", False) and block:
                    s.blocked[case.scenario_id] = "; ".join(block)
    repair_cases = [c for c in cases if c.suite == "repair" and any(not getattr(s, "realistic", False) for s in systems)]
    prepared = await asyncio.gather(*(prepare_repair(c, engine, run_dir / "_inputs" / c.scenario_id,
                                                     reuse_inputs / c.scenario_id if reuse_inputs else None)
                                      for c in repair_cases))
    repairs = {c.scenario_id: p for c, p in zip(repair_cases, prepared)}

    done = 0
    total = len(cases) * len(systems)

    async def one(system, case: Case) -> None:
        nonlocal done
        # The engine has its own worker limit (fair latency); the semaphore here bounds API calls.
        async with (contextlib.nullcontext() if isinstance(system, ShiftwrightSystem) else sem):
            if getattr(system, "realistic", False):
                out = await system.run_realistic(case)
            elif getattr(system, "replay", False):
                out = system.run(case.scenario_id)
            elif case.suite == "repair":
                r = repairs[case.scenario_id]
                callouts: list[CallOut] = r["callouts"]
                out = await system.repair(case.config, r["base"], callouts, r["day"], r["now"])
            else:
                out = await system.weekly(case.config)
        write_run(run_dir / system_slug(system.name) / case.scenario_id, system.name, case, out)
        done += 1
        lat = f"{out.latency_s:.1f}s" if out.latency_s is not None else "-"
        log(f"[{done:3d}/{total}] {system.name:32s} {case.scenario_id:36s} {out.outcome:12s} {lat}")

    pairs = [(s, c) for s in systems for c in cases
             if (c.suite == "realistic") == bool(getattr(s, "realistic", False))]
    total = len(pairs)
    await asyncio.gather(*(one(s, c) for s, c in pairs))
