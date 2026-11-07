"""Run shiftwright_engine.solve_week (black box) on scenarios and validate every schedule.

    uv run python packages/validator/scripts/audit_engine.py [--time 30] [--json out.json]

Prints one line per case and every hard violation / metrics_mismatch (a disagreement).
"""
from __future__ import annotations

import argparse
import json
import time

from shiftwright_validator.audit import audit_cases, default_cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=30)
    ap.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3])
    ap.add_argument("--json")
    args = ap.parse_args()
    results = []
    for result in audit_cases(default_cases(args.seeds), time_limit_s=args.time):
        results.append(result)
        print(result.line(), flush=True)
        for d in result.disagreements:
            print("    DISAGREE", d)
        if result.status != "infeasible":
            for d in result.expected:
                print("    expected", d)
    bad = [r for r in results if r.disagreements]
    print(f"\n{len(results)} cases, {len(bad)} with disagreements, "
          f"{sum(len(r.disagreements) for r in results)} disagreements total")
    if args.json:
        with open(args.json, "w") as f:
            json.dump([r.as_dict() for r in results], f, indent=1)


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"{time.time() - t0:.0f}s")
