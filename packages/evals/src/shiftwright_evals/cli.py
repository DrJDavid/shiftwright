"""`python -m shiftwright_evals [--quick] [--mock-baselines] ...`

Real baselines run only when OPENROUTER_API_KEY and BASELINE_MODELS are both set (and
--mock-baselines is not given). Otherwise baselines are skipped with a note.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .llm import BudgetGuard, CachedClient, MockClient, OpenRouterClient
from .mock import MOCK_MODELS
from .report import build
from .runner import run_all
from .suites import SUITES, build_cases
from .systems import BaselineSystem, ShiftwrightSystem

PKG_ROOT = Path(__file__).resolve().parents[2]  # packages/evals


def parse_args(argv):
    p = argparse.ArgumentParser(prog="shiftwright_evals", description=__doc__)
    p.add_argument("--quick", action="store_true", help="1 seed, S+M only")
    p.add_argument("--mock-baselines", action="store_true", help="canned bad outputs instead of real models")
    p.add_argument("--suites", default="weekly,honesty,repair", help=f"comma list from {SUITES}")
    p.add_argument("--models", default=None, help="override BASELINE_MODELS (comma list)")
    p.add_argument("--no-engine", action="store_true", help="skip the Shiftwright engine (reported unavailable)")
    p.add_argument("--engine-time-limit", default="S=30,M=30,L=60",
                   help="seconds per solve: a number, or per size like S=30,M=30,L=60")
    p.add_argument("--fix-time-limit", type=float, default=10.0)
    p.add_argument("--engine-workers", type=int, default=2, help="concurrent engine solves")
    p.add_argument("--max-output-tokens", type=int, default=None,
                   help="cap baseline max_tokens (default: as high as each model allows)")
    p.add_argument("--budget-usd", type=float, default=None,
                   help="stop new paid calls if spend + projection exceeds this (uses OpenRouter usage.cost)")
    p.add_argument("--concurrency", type=int, default=4, help="max concurrent baseline API calls")
    p.add_argument("--out-dir", type=Path, default=PKG_ROOT / "runs")
    p.add_argument("--reports-dir", type=Path, default=PKG_ROOT / "reports")
    p.add_argument("--cache-dir", type=Path, default=PKG_ROOT / ".cache")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--report-only", metavar="RUN_ID", default=None,
                   help="rebuild the report for an existing run folder; runs nothing")
    return p.parse_args(argv)


def parse_limits(text: str) -> float | dict:
    if "=" not in text:
        return float(text)
    return {k.strip(): float(v) for k, v in (part.split("=") for part in text.split(",") if part.strip())}


async def _amain(args) -> int:
    t0 = time.perf_counter()
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.out_dir / run_id
    report_dir = args.reports_dir / run_id
    cache_dir = None if args.no_cache else args.cache_dir
    suites = [s.strip() for s in args.suites.split(",") if s.strip()]

    engine = ShiftwrightSystem(enabled=not args.no_engine, time_limit_s=parse_limits(args.engine_time_limit),
                               fix_time_limit_s=args.fix_time_limit, cache_dir=cache_dir,
                               workers=args.engine_workers)
    systems: list = [engine]
    notes = []
    real_client = None
    guard = None
    if args.mock_baselines:
        client = CachedClient(MockClient(), cache_dir / "llm-mock" if cache_dir else None)
        systems += [BaselineSystem(m, client, mock=True) for m in MOCK_MODELS]
    else:
        models = [m.strip() for m in (args.models or os.environ.get("BASELINE_MODELS", "")).split(",") if m.strip()]
        if not models or not os.environ.get("OPENROUTER_API_KEY"):
            notes.append("baselines skipped: set OPENROUTER_API_KEY and BASELINE_MODELS, or pass --mock-baselines")
            client = CachedClient(MockClient(), None)
        else:
            real_client = OpenRouterClient(max_output_cap=args.max_output_tokens)
            paid = real_client
            if args.budget_usd is not None:
                planned = len(build_cases(suites, args.quick)) * len(models)
                paid = guard = BudgetGuard(real_client, args.budget_usd, planned)
            client = CachedClient(paid, cache_dir / "llm" if cache_dir else None)
            systems += [BaselineSystem(m, client) for m in models]
    for n in notes:
        print(f"note: {n}", file=sys.stderr)

    cases = build_cases(suites, args.quick)
    print(f"run {run_id}: {len(cases)} scenarios x {len(systems)} systems -> {run_dir}")
    if not engine.available:
        print(f"note: shiftwright unavailable: {engine.unavailable_reason}", file=sys.stderr)
    try:
        await run_all(cases, systems, run_dir, concurrency=args.concurrency)
    finally:
        if real_client:
            await real_client.aclose()

    manifest = {
        "run_id": run_id, "quick": args.quick, "mock_baselines": args.mock_baselines, "suites": suites,
        "scenarios": [c.scenario_id for c in cases],
        "systems": [{"name": s.name, "available": s.available, "unavailable_reason": s.unavailable_reason,
                     **({"engine_source_hash": s.src_hash, "fix_day": s.can_fix} if s is engine else {})}
                    for s in systems],
        "llm_calls": {"hits": client.hits, "misses": client.misses},
        "engine_calls": {"hits": engine.hits, "misses": engine.misses},
        "openrouter_spend_usd": round(guard.spent, 4) if guard else None,
        "budget_stopped": guard.stopped if guard else None,
        "notes": notes,
        "started": datetime.now().isoformat(timespec="seconds"),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    out = build(run_dir, report_dir, manifest)
    print(f"report: {out}  ({manifest['wall_s']} s; llm cache {client.hits} hits / {client.misses} misses)")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.report_only:
        run_dir = args.out_dir / args.report_only
        manifest = json.loads((run_dir / "manifest.json").read_text())
        print(f"report: {build(run_dir, args.reports_dir / args.report_only, manifest)}")
        return 0
    return asyncio.run(_amain(args))
