"""Readiness checks, in the order API.md lists them."""
from __future__ import annotations

from datetime import date

from shiftwright_contracts.models import LawPack, LawRuleType, RuleStatus, StoreConfig

from . import integrations
from .models import Readiness, ReadinessCheck

NON_BLOCKING = {"provisional_rules"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def compute(config: StoreConfig, equipment_review: dict[str, str] | None = None) -> Readiness:
    """`equipment_review`: kv state from equipment.py ({role_id: auto|confirmed|rejected})."""
    checks: list[ReadinessCheck] = []

    def add(id_: str, label: str, ok: bool, detail: str) -> None:
        checks.append(ReadinessCheck(id=id_, label=label, ok=ok, detail=detail))

    s = config.store
    open_days = sorted({h.day for h in s.hours if h.close > h.open})
    add("store_basics", "Store basics", bool(s.name.strip()) and bool(open_days),
        f"{s.name}, {s.jurisdiction.state}{'/' + s.jurisdiction.city if s.jurisdiction.city else ''}, "
        f"{len(open_days)} open days, {s.slot_minutes}-min slots" if open_days else "Store hours not set.")

    pack: LawPack | None = None
    try:
        pack = integrations.resolve_law(s.jurisdiction)
        add("jurisdiction", "Labor law resolved", True,
            f"{pack.coverage}, {len(pack.rules)} rules" + (f" — {'; '.join(pack.warnings)}" if pack.warnings else ""))
    except Exception as e:  # resolver raised: show it, block
        add("jurisdiction", "Labor law resolved", False, f"Could not resolve law for {s.jurisdiction.state}: {e}")

    add("roles", "Roles", bool(config.roles), f"{len(config.roles)} roles" if config.roles else "No roles yet.")
    add("employees", "Employees", bool(config.employees),
        f"{len(config.employees)} employees" if config.employees else "No employees yet.")

    trained = {r for e in config.employees for r in e.trained_role_ids}
    untrained = [r.name for r in config.roles if r.id not in trained]
    add("training", "Every role has a trained employee", bool(config.roles) and not untrained,
        "All roles covered." if config.roles and not untrained else
        ("No roles yet." if not config.roles else f"Nobody trained for: {', '.join(untrained)}"))

    demand_days = {d.day for d in config.demand if d.headcount > 0}
    missing = [d for d in open_days if d not in demand_days]
    add("demand", "Demand for every open day", bool(open_days) and not missing,
        "Demand set for all open days." if open_days and not missing else
        ("Store hours not set." if not open_days else f"No demand on {', '.join(DAY_NAMES[d] for d in missing)}"))

    demand_roles = {d.role_id for d in config.demand if d.headcount > 0}
    unpriced = [r.name for r in config.roles if r.id in demand_roles and r.gap_penalty_per_hour <= 0]
    add("priorities", "Role priorities set", bool(demand_roles) and not unpriced,
        ("No demand yet." if not demand_roles else
         "Every role with demand has a gap cost." if not unpriced else
         f"Set priorities (what an uncovered hour costs) for: {', '.join(unpriced)}. "
         "At $0/h the solver would leave them empty."))

    names = {r.id: r.name for r in config.roles}
    review = equipment_review or {}
    auto = [names[r] for r, st in review.items() if st == "auto" and r in names]
    tagged = [names[r] for r, tags in config.role_tags.items() if "powered_industrial_truck" in tags and r in names]
    # ok: the protective tag is already applied; this lists what the leader should confirm or reject.
    add("equipment_roles", "Powered-equipment roles", True,
        (f"Tagged automatically as powered industrial trucks, so minor-labor rules apply: {', '.join(auto)}. "
         "Please confirm or reject.") if auto else
        (f"Powered industrial truck roles: {', '.join(tagged)}." if tagged else "No powered-equipment roles."))

    b = config.budget
    add("budget", "Payroll budget", b.weekly_hours_cap > 0,
        f"{b.weekly_hours_cap:g} hours/week cap" if b.weekly_hours_cap > 0 else "Weekly hours cap not set.")

    floor = minimum_wage(pack, s.week_start) if pack else None
    if floor is None:
        add("minimum_wage", "Wages at or above minimum wage", pack is not None,
            "Labor law not resolved; cannot check wages." if pack is None else "No minimum-wage rule in the law pack.")
    else:
        rate, rule_id = floor
        low = [e for e in config.employees if e.wage_per_hour < rate]
        add("minimum_wage", "Wages at or above minimum wage", not low,
            f"All wages ≥ ${rate:.2f}/hr ({rule_id})." if not low else
            f"Below the ${rate:.2f}/hr minimum ({rule_id}): "
            + ", ".join(f"{e.name} (${e.wage_per_hour:.2f})" for e in low))

    prov = [c.note or c.kind.value.replace("_", " ") for c in config.constraints
            if c.status == RuleStatus.provisional]
    add("provisional_rules", "No unconfirmed rules", not prov,
        "None." if not prov else f"{len(prov)} unconfirmed rule(s), not used until confirmed: {'; '.join(prov)}")

    ready = all(c.ok for c in checks if c.id not in NON_BLOCKING)
    return Readiness(ready=ready, checks=checks)


def minimum_wage(pack: LawPack, on: date) -> tuple[float, str] | None:
    """Highest minimum_wage rule in effect on `on` (most protective wins), as (rate, rule id)."""
    best: tuple[float, str] | None = None
    for r in pack.rules:
        if r.type != LawRuleType.minimum_wage:
            continue
        eff = r.params.get("effective")
        try:
            if eff and date.fromisoformat(str(eff)) > on:
                continue
            rate = float(r.params["dollars_per_hour"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or rate > best[0]:
            best = (rate, r.id)
    return best
