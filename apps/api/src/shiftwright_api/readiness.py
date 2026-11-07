"""Readiness checks, in the order API.md lists them."""
from __future__ import annotations

from shiftwright_contracts.models import RuleStatus, StoreConfig

from . import integrations
from .models import Readiness, ReadinessCheck

NON_BLOCKING = {"provisional_rules"}


def compute(config: StoreConfig) -> Readiness:
    checks: list[ReadinessCheck] = []

    def add(id_: str, label: str, ok: bool, detail: str) -> None:
        checks.append(ReadinessCheck(id=id_, label=label, ok=ok, detail=detail))

    s = config.store
    open_days = sorted({h.day for h in s.hours if h.close > h.open})
    add("store_basics", "Store basics", bool(s.name.strip()) and bool(open_days),
        f"{s.name}, {s.jurisdiction.state}{'/' + s.jurisdiction.city if s.jurisdiction.city else ''}, "
        f"{len(open_days)} open days, {s.slot_minutes}-min slots" if open_days else "Store hours not set.")

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
    untrained = [r.id for r in config.roles if r.id not in trained]
    add("training", "Every role has a trained employee", bool(config.roles) and not untrained,
        "All roles covered." if config.roles and not untrained else
        ("No roles yet." if not config.roles else f"Nobody trained for: {', '.join(untrained)}"))

    demand_days = {d.day for d in config.demand if d.headcount > 0}
    missing = [d for d in open_days if d not in demand_days]
    add("demand", "Demand for every open day", bool(open_days) and not missing,
        "Demand set for all open days." if open_days and not missing else
        ("Store hours not set." if not open_days else f"No demand on day(s): {', '.join(map(str, missing))}"))

    b = config.budget
    add("budget", "Payroll budget", b.weekly_hours_cap > 0,
        f"{b.weekly_hours_cap:g} hours/week cap" if b.weekly_hours_cap > 0 else "Weekly hours cap not set.")

    prov = [c.id for c in config.constraints if c.status == RuleStatus.provisional]
    add("provisional_rules", "No unconfirmed rules", not prov,
        "None." if not prov else f"{len(prov)} provisional rule(s) not used until confirmed: {', '.join(prov)}")

    ready = all(c.ok for c in checks if c.id not in NON_BLOCKING)
    return Readiness(ready=ready, checks=checks)
