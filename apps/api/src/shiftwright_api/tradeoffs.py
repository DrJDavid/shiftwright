"""The engine's build tradeoffs (`solver_stats.tradeoffs`, SEMANTICS #25) as manager decisions.

Every build (REST /solve, the agent's dry_run_solve) saves its tradeoffs here. Each becomes a `tradeoff`
card whose question and options are written from the solve's own numbers (no LLM arithmetic):
  budget_gap       "Covering Cashier Tue 2–4 pm needs 3 hours over your budget ($51). Approve the hours, or
                    leave it open?"  approve → a leader budget approval (+extra_hours); leave_open → nothing.
  preference_cost  "Keeping "<rule>" costs $120 more this week. Keep it?"  keep → nothing; drop → the rule is
                    rejected (it no longer applies).
`if_kept` = the week with the budget / rule as it is; `if_dropped` = the what-if.
"""
from __future__ import annotations

from typing import Any, Optional

from shiftwright_contracts.models import Schedule, StoreConfig

from .explain import DAYS, clock, money

_KV = "build_tradeoffs"


def from_schedule(sched: Schedule) -> list[dict]:
    """The schedule's tradeoffs, biggest wage difference first (the engine's order; kept stable)."""
    items = [t for t in (sched.solver_stats or {}).get("tradeoffs") or [] if isinstance(t, dict) and t.get("id")]
    return sorted(items, key=lambda t: -abs(_diff(t)))


def save(db: Any, store_id: str, sched: Schedule) -> list[dict]:
    items = from_schedule(sched)
    db.put(store_id, _KV, "latest", items)
    db.put(store_id, _KV, "answered", {})
    return items


def latest(db: Any, store_id: str) -> list[dict]:
    return db.get(store_id, _KV, "latest") or []


def answered(db: Any, store_id: str) -> dict[str, str]:
    return db.get(store_id, _KV, "answered") or {}


def mark_answered(db: Any, store_id: str, tradeoff_id: str, option: str) -> None:
    done = answered(db, store_id)
    done[tradeoff_id] = option
    db.put(store_id, _KV, "answered", done)


def _diff(t: dict) -> float:
    """if_dropped − if_kept wage cost."""
    return float(t["if_dropped"]["wage_cost"]) - float(t["if_kept"]["wage_cost"])


def _hours(x: float) -> str:
    return f"{x:g} hour" + ("" if x == 1 else "s")


def _coverage(t: dict) -> str:
    a, b = t["if_kept"].get("coverage_pct"), t["if_dropped"].get("coverage_pct")
    return f"coverage {a:.1f}% → {b:.1f}%" if a is not None and b is not None else ""


def _where(cfg: StoreConfig, t: dict) -> str:
    role = next((r.name for r in cfg.roles if r.id == t.get("role_id")), t.get("role_id") or "")
    day = DAYS[t["day"]] if isinstance(t.get("day"), int) else ""
    win = t.get("window") or []
    when = f"{clock(win[0])}–{clock(win[1])}" if len(win) == 2 else ""
    return " ".join(x for x in (role, day, when) if x)


def rule_text(cfg: StoreConfig, rule_id: Optional[str]) -> str:
    c = next((c for c in cfg.constraints if c.id == rule_id), None)
    if c is None:
        return rule_id or "this rule"
    if c.note:
        return c.note
    names = {e.id: e.name for e in cfg.employees}
    who = [names.get(x, x) for x in (c.params.get("employee_ids") or [c.params.get("employee_id")]) if x]
    return c.kind.value.replace("_", " ") + (f" ({', '.join(who)})" if who else "")


def card(cfg: StoreConfig, t: dict) -> dict:
    """`tradeoff` card props {question, options, tradeoff} from one engine tradeoff."""
    tid = t["id"]
    cov = _coverage(t)
    if t["kind"] == "budget_gap":
        extra = float(t.get("extra_hours") or (t["if_dropped"]["hours"] - t["if_kept"]["hours"]))
        cost = max(_diff(t), 0.0)
        where = _where(cfg, t)
        question = (f"Covering {where} needs {_hours(extra)} over your budget ({money(cost)}). "
                    "Approve the hours, or leave it open?")
        options = [
            {"id": f"{tid}:approve", "label": f"Approve {_hours(extra)}", "cost_dollars": round(cost, 2),
             "effect": f"Covers {where} on the next build" + (f"; {cov}" if cov else "") + "."},
            {"id": f"{tid}:leave_open", "label": "Leave it open", "cost_dollars": 0.0,
             "effect": "Stays within your hours budget; that time stays uncovered."},
        ]
    else:
        saving = max(-_diff(t), 0.0)
        rule = rule_text(cfg, t.get("rule_id"))
        question = f'Keeping "{rule}" costs {money(saving)} more this week. Keep it?'
        options = [
            {"id": f"{tid}:keep", "label": "Keep the rule", "cost_dollars": round(saving, 2),
             "effect": "The schedule keeps following it."},
            {"id": f"{tid}:drop", "label": "Drop the rule", "cost_dollars": 0.0,
             "effect": f"Saves {money(saving)} on the next build" + (f"; {cov}" if cov else "") + "."},
        ]
    return {"question": question, "options": options, "tradeoff": t}


def summaries(cfg: StoreConfig, items: list[dict], done: Optional[dict] = None) -> list[dict]:
    done = done or {}
    return [{"id": t["id"], "kind": t["kind"], "question": card(cfg, t)["question"],
             "answered": done.get(t["id"])} for t in items]
