"""Audit shiftwright_engine.fix_day (black box) with validate_fix.

    uv run python packages/validator/scripts/audit_fix.py [--time 20] [--seeds 1 2 3]
           [--jurisdictions "WA seattle" "PA philadelphia" ...]

1. Demo stores (Austin, Chicago, Seattle, SF), Saturday 06:04, call-outs e034/e052/e053 (the demo
   script), for outreach_mode None / one_to_one / group_offer; optionally the Austin store moved into
   each predictive-scheduling jurisdiction (--all-fww / --jurisdictions).
2. S scenarios (easy/normal/tight/messy TX) via pick_callouts on the scenario's call-out day.
"""
from __future__ import annotations

import argparse
from collections import Counter

from shiftwright_contracts.models import Jurisdiction

from shiftwright_validator.audit import Case, audit_fix, default_cases, with_law_pack

MODES = (None, "one_to_one", "group_offer")
FWW = ["WA seattle", "IL chicago", "IL evanston", "CA los angeles", "CA san francisco", "CA berkeley",
       "CA emeryville", "PA philadelphia", "NY new york", "OR -"]


def report(results) -> None:
    for r in results:
        print(r.line(), flush=True)
        kinds = Counter(d.split(" ")[0] + (" premium" if "Predictive-scheduling" in d else "")
                        for d in r.disagreements)
        if kinds:
            print("    ", dict(kinds))
        for d in r.disagreements[:4]:
            print("    DISAGREE", d[:240])


def main() -> None:
    from shiftwright_engine import solve_week
    from shiftwright_laws import resolve
    from shiftwright_scenarios import generate, load_demo_store

    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=20)
    ap.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3])
    ap.add_argument("--jurisdictions", nargs="*", default=[])
    ap.add_argument("--all-fww", action="store_true", help="all 10 predictive-scheduling jurisdictions")
    args = ap.parse_args()

    for locality in ("austin", "chicago", "seattle", "sf"):
        case = Case(f"demo:{locality}", with_law_pack(load_demo_store(locality)))
        schedule = solve_week(case.config, time_limit_s=30)
        report(audit_fix(case, schedule, day=5, now=364, modes=MODES,
                         callout_ids=["e034", "e052", "e053"]))
    for place in (FWW if args.all_fww else args.jurisdictions):
        config = load_demo_store()
        state, city = place.split(" ", 1)
        config.store.jurisdiction = Jurisdiction(state=state, city=None if city == "-" else city)
        config.law_pack = resolve(config.store.jurisdiction)
        case = Case(f"demo@{place}", with_law_pack(config))
        schedule = solve_week(case.config, time_limit_s=30)
        report(audit_fix(case, schedule, day=5, now=364, modes=MODES,
                         callout_ids=["e034", "e052", "e053"]))

    for difficulty in ("easy", "normal", "tight", "messy"):
        for seed in args.seeds:
            sc = generate(seed, "S", difficulty, "TX")
            case = Case(f"S/{difficulty}/TX/{seed}", with_law_pack(sc.config))
            schedule = solve_week(case.config, time_limit_s=args.time)
            if schedule.status not in ("optimal", "feasible"):
                print(case.name, "no schedule:", schedule.status)
                continue
            report(audit_fix(case, schedule, day=sc.expected.get("callout_day", 5)))


if __name__ == "__main__":
    main()
