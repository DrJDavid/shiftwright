"""Readiness checks, in the order API.md lists them."""
from __future__ import annotations

from datetime import date

from shiftwright_contracts.models import LawPack, LawRuleType, RuleStatus, StoreConfig

from . import integrations
from .models import Readiness, ReadinessCheck

NON_BLOCKING = {"provisional_rules"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def compute(config: StoreConfig, equipment_review: dict | None = None) -> Readiness:
    """`equipment_review`: kv state from equipment.state(). Checks carry `severity` ok | warn | block
    (warn = shown, never blocks)."""
    checks: list[ReadinessCheck] = []

    def add(id_: str, label: str, ok: bool, detail: str, severity: str | None = None) -> None:
        sev = severity or ("ok" if ok else ("warn" if id_ in NON_BLOCKING else "block"))
        checks.append(ReadinessCheck(id=id_, label=label, ok=ok, detail=detail, severity=sev))

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
    auto = [f"{names[r]} ({', '.join(v.get('tags') or [])})" for r, v in review.items()
            if isinstance(v, dict) and v.get("status") == "auto" and r in names]
    tagged = {r: tags for r, tags in config.role_tags.items() if tags and r in names}
    # ok: the protective tags are already applied; this lists what the leader should confirm or reject.
    add("equipment_roles", "Hazard and equipment roles", True,
        (f"Tagged automatically, so minor-labor rules apply: {'; '.join(auto)}. Please confirm or reject.") if auto
        else ("Tagged roles: " + "; ".join(f"{names[r]} ({', '.join(t)})" for r, t in tagged.items()) + "."
              if tagged else "No hazard or equipment roles tagged."), severity="warn" if auto else "ok")

    bans = [rl for rl in (pack.rules if pack else []) if rl.type == LawRuleType.minor_prohibited_roles]

    def banned_by(age: int, tags: list[str]) -> list[str]:
        return [rl.id for rl in bans if set(rl.params.get("role_tags") or []) & set(tags)
                and (rl.params.get("age_min") or 0) <= age < int(rl.params.get("age_below") or 0)]
    minors = {r: [e for e in config.employees if e.age < 18 and r in e.trained_role_ids] for r in tagged}
    minors = {r: v for r, v in minors.items() if v}

    def who(r: str) -> str:
        return ", ".join(f"{e.name} ({e.age}" + (f"; barred by {', '.join(banned_by(e.age, tagged[r]))})"
                                                 if banned_by(e.age, tagged[r]) else ")") for e in minors[r])
    add("minors_on_tagged_roles", "Minors trained on tagged roles", True,
        ("The schedule keeps these people off roles the law pack bars at their age: " + "; ".join(
            f"{names[r]} ({', '.join(tagged[r])}): {who(r)}" for r in minors) + ".") if minors
        else "No minors trained on tagged roles.", severity="warn" if minors else "ok")

    add("business_type", "Business type", True,
        f"{s.sector.value}" + (f": {s.business_description}" if s.business_description else "") if s.sector
        else "Business type not set; every sector's labor rules are applied to be safe.",
        severity="ok" if s.sector else "warn")

    est = sorted({d.role_id for d in config.demand if d.source.value == "estimate"})
    add("staffing_draft", "Staffing levels confirmed", True,
        "Staffing levels are a draft (estimated, not confirmed) for: " + ", ".join(names.get(r, r) for r in est)
        + ". Confirm them on a staffing card." if est else "No draft staffing.",
        severity="warn" if est else "ok")

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
        # SEMANTICS #20/#15: tipped cash wages vs tipped_minimum_wage, or the full minimum when there is none
        tipped_roles = {r.id for r in config.roles if r.tipped}
        tip = minimum_wage(pack, s.week_start, LawRuleType.tipped_minimum_wage, "cash_wage_per_hour")
        t_rate, t_rule = tip if tip else (rate, rule_id)
        low_tip = [e for e in config.employees if e.tipped_wage_per_hour is not None
                   and tipped_roles & set(e.trained_role_ids) and e.tipped_wage_per_hour < t_rate]
        parts = []
        if low:
            parts.append(f"Below the ${rate:.2f}/hr minimum ({rule_id}): "
                         + ", ".join(f"{e.name} (${e.wage_per_hour:.2f})" for e in low))
        if low_tip:
            parts.append(f"Tipped cash wage below ${t_rate:.2f}/hr ({t_rule}"
                         + ("" if tip else "; no tipped minimum wage in the law pack, so the full minimum applies")
                         + "): " + ", ".join(f"{e.name} (${e.tipped_wage_per_hour:.2f})" for e in low_tip))
        add("minimum_wage", "Wages at or above minimum wage", not (low or low_tip),
            f"All wages ≥ ${rate:.2f}/hr ({rule_id})." if not parts else " ".join(parts))

    prov = [c.note or c.kind.value.replace("_", " ") for c in config.constraints
            if c.status == RuleStatus.provisional]
    add("provisional_rules", "No unconfirmed rules", not prov,
        "None." if not prov else f"{len(prov)} unconfirmed rule(s), not used until confirmed: {'; '.join(prov)}")

    ready = all(c.ok for c in checks if c.id not in NON_BLOCKING)
    return Readiness(ready=ready, checks=checks)


def minimum_wage(pack: LawPack, on: date, rule_type: LawRuleType = LawRuleType.minimum_wage,
                 key: str = "dollars_per_hour") -> tuple[float, str] | None:
    """Highest rule of `rule_type` in effect on `on` (most protective wins), as (rate, rule id)."""
    best: tuple[float, str] | None = None
    for r in pack.rules:
        if r.type != rule_type:
            continue
        eff = r.params.get("effective")
        try:
            if eff and date.fromisoformat(str(eff)) > on:
                continue
            rate = float(r.params[key])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or rate > best[0]:
            best = (rate, r.id)
    return best
