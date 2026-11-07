"""Agent tools: cards (pause for the leader), mutations (validated config edits), reads/computes.

Every tool returns a JSON-able dict that becomes the tool result the LLM sees. Mutations go
through `Database.mutate`, which validates the whole config against the contracts; failures
come back to the LLM as `{"error": ..., "details": [...]}` and nothing is saved.

Card tools return a `CardRequest`; the loop emits the `card` SSE event, waits for the result,
then calls `apply(result)`. Card results that carry config (store_basics, payroll, roles,
training_matrix, coverage_grid, events, propose_rule, employee_availability) are applied by
the server directly (actor "leader"), so the config never depends on the LLM re-typing them.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Union

from pydantic import BaseModel, ValidationError

from shiftwright_contracts.models import (
    Constraint,
    EventKind,
    Jurisdiction,
    LawRuleType,
    Role,
    RuleStatus,
    StoreConfig,
)

from .. import equipment, integrations, readiness
from ..db import ConfigInvalid, Database


# --------------------------------------------------------------------------- #
@dataclass
class ToolResult:
    content: dict
    patch_summary: Optional[list[str]] = None  # set => emit a `config` event
    config_version: Optional[int] = None


@dataclass
class CardRequest:
    card_type: str
    props: dict
    apply: Callable[[dict], Union[ToolResult, Awaitable[ToolResult]]]
    blocking: bool = True  # False: shown read-only, the turn does not wait for a result


@dataclass
class ToolContext:
    db: Database
    store_id: str
    actor: str = "agent"

    def config(self) -> StoreConfig:
        return self.db.get_config(self.store_id)

    def mutate(self, tool: str, args: dict, fn: Callable[[dict], Any], summary: list[str],
               actor: Optional[str] = None) -> ToolResult:
        tagged: list = []
        if tool in ("upsert_role", "card:roles"):
            review = equipment.state(self.db, self.store_id)
            inner = fn

            def fn(d):  # noqa: F811 - same mutation, plus powered-equipment tagging
                out = inner(d)
                if out is not None:
                    d = out
                tagged.extend(equipment.tag_in_dict(d, review))
                return out
        try:
            cfg = self.db.mutate(self.store_id, fn, tool, args, actor or self.actor)
        except ConfigInvalid as e:
            return ToolResult({"error": "Config change rejected by contract validation; nothing saved.",
                               "details": _short_errors(e.errors)})
        except ToolError as e:
            return ToolResult({"error": str(e)})
        content: dict = {"ok": True, "config_version": cfg.config_version, "changed": summary}
        if tagged:
            equipment.record_auto(self.db, self.store_id, tagged)
            summary = summary + [f"tagged as powered equipment: {', '.join(n for _, n in tagged)}"]
            content.update(changed=summary, equipment_tagged=[rid for rid, _ in tagged],
                           note="These look like powered industrial trucks, so minor-labor rules now apply. "
                                "Tell the leader and ask them to confirm or reject (review_equipment_role).")
        return ToolResult(content, patch_summary=summary, config_version=cfg.config_version)


class ToolError(ValueError):
    """Raised inside a mutation fn to abort with a message for the LLM."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], Any]
    kind: str = "read"  # card | mutation | read

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def _short_errors(errors: list[dict]) -> list[dict]:
    return [{"loc": ".".join(str(x) for x in e.get("loc", ())), "msg": e.get("msg"), "input": str(e.get("input"))[:120]}
            for e in errors[:10]]


def _schema(model: type[BaseModel]) -> dict:
    """Inline JSON schema of a contract model for tool parameters."""
    return model.model_json_schema()


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _upsert(items: list[dict], item: dict, key: str = "id") -> str:
    for i, existing in enumerate(items):
        if existing.get(key) == item.get(key):
            items[i] = item
            return "updated"
    items.append(item)
    return "added"


def _cancelled(result: dict) -> bool:
    return bool(result.get("cancelled"))


CANCELLED = ToolResult({"cancelled": True, "note": "The leader cancelled the card. Nothing changed."})

# --------------------------------------------------------------------------- #
# Card tools
# --------------------------------------------------------------------------- #
PREFILL = _obj({"prefill": {"type": "object", "description": "Optional values you already heard, to prefill the card."}})


def ask_store_basics(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    props = cfg.store.model_dump(mode="json")
    props.update({k: v for k, v in (args.get("prefill") or {}).items() if k != "id"})

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        fields = {k: v for k, v in result.items() if k != "id"}

        def fn(d):
            d["store"].update(fields)
        return ctx.mutate("card:store_basics", fields, fn, [f"store.{k}" for k in fields], actor="leader")
    return CardRequest("store_basics", props, apply)


def ask_payroll(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    props = cfg.budget.model_dump(mode="json")
    props.update({k: v for k, v in (args.get("prefill") or {}).items() if k != "approvals"})

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        fields = {k: v for k, v in result.items() if k != "approvals"}  # approvals only via tradeoff

        def fn(d):
            d["budget"].update(fields)
        return ctx.mutate("card:payroll", fields, fn, [f"budget.{k}" for k in fields], actor="leader")
    return CardRequest("payroll", props, apply)


def ask_roles(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    props = {"departments": [d.model_dump(mode="json") for d in cfg.departments],
             "roles": [r.model_dump(mode="json") for r in cfg.roles]}
    for key in ("departments", "roles"):
        for item in args.get(key) or []:
            _upsert(props[key], item)

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED

        def fn(d):
            d["departments"] = result.get("departments", d["departments"])
            d["roles"] = result.get("roles", d["roles"])
        return ctx.mutate("card:roles", result, fn,
                          [f"{len(result.get('departments', []))} departments, {len(result.get('roles', []))} roles"],
                          actor="leader")
    return CardRequest("roles", props, apply)


def ask_training_matrix(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    props = {"employees": [{"id": e.id, "name": e.name, "trained_role_ids": e.trained_role_ids} for e in cfg.employees],
             "roles": [r.model_dump(mode="json") for r in cfg.roles]}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED

        def fn(d):
            known = {e["id"] for e in d["employees"]}
            unknown = [k for k in result if k not in known]
            if unknown:
                raise ToolError(f"Unknown employee ids in training matrix: {unknown}")
            for e in d["employees"]:
                if e["id"] in result:
                    e["trained_role_ids"] = list(result[e["id"]])
        return ctx.mutate("card:training_matrix", result, fn, [f"training for {len(result)} employees"], actor="leader")
    return CardRequest("training_matrix", props, apply)


DAY_TYPES = {"weekday", "saturday", "sunday", "truck_day", "custom"}


def _days_for(cfg: StoreConfig, day_type: str) -> list[int]:
    open_days = sorted({h.day for h in cfg.store.hours if h.close > h.open})
    if day_type == "custom":
        return open_days
    truck = {e.day for e in cfg.events if e.kind == EventKind.truck}
    if day_type == "truck_day":
        return [d for d in open_days if d in truck]
    if day_type == "saturday":
        return [d for d in open_days if d == 5 and d not in truck]
    if day_type == "sunday":
        return [d for d in open_days if d == 6 and d not in truck]
    return [d for d in open_days if d < 5 and d not in truck]


def _window(cfg: StoreConfig, days: list[int]) -> tuple[int, int]:
    """Open − pre_open .. close + post_close, widened to cover events on those days (e.g. a 4am truck)."""
    hrs = [h for h in cfg.store.hours if h.day in days]
    if not hrs:
        return 0, 0
    start = min(h.open for h in hrs) - cfg.store.pre_open_minutes
    end = max(h.close for h in hrs) + cfg.store.post_close_minutes
    for e in cfg.events:
        if e.day in days:
            start, end = min(start, e.start), max(end, e.end)
    slot = cfg.store.slot_minutes
    return max(0, start - start % slot), end


def ask_coverage_grid(ctx: ToolContext, args: dict) -> CardRequest:
    """Grid semantics (API extension, documented in STATUS.md): props carry `start_minute` and
    `days`; prefill[role_id][i] is the headcount for slot [start_minute + i*slot, +slot)."""
    cfg = ctx.config()
    day_type = args.get("day_type", "weekday")
    if day_type not in DAY_TYPES:
        day_type = "weekday"
    if day_type == "truck_day" and not any(e.kind == EventKind.truck for e in cfg.events):
        day_type = "custom"  # v1.5: truck_day only when the store has truck events
    if args.get("days"):
        day_type = "custom" if day_type != "truck_day" else day_type
    days = sorted(set(args.get("days") or _days_for(cfg, day_type)))
    slot = cfg.store.slot_minutes
    start, end = _window(cfg, days)
    n = max(0, (end - start) // slot)
    roles = [r.model_dump(mode="json") for r in cfg.roles]
    prefill: dict[str, list[int]] = {r.id: [0] * n for r in cfg.roles}
    if days:
        ref = days[0]
        for dm in cfg.demand:
            if dm.day == ref and dm.role_id in prefill:
                for i in range(n):
                    t = start + i * slot
                    if dm.start <= t < dm.end:
                        prefill[dm.role_id][i] += dm.headcount
    props = {"day_type": day_type, "days": days, "roles": roles, "slot_minutes": slot,
             "start_minute": start, "prefill": prefill}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        grid: dict[str, list[int]] = result.get("prefill") or result.get("grid") or result
        grid = {k: v for k, v in grid.items() if isinstance(v, list)}

        def fn(d):
            keep = [x for x in d["demand"]
                    if not (x["day"] in days and x["role_id"] in grid and x["source"] != "event")]
            new = []
            for role_id, counts in grid.items():
                for day in days:
                    i = 0
                    while i < len(counts):
                        hc = int(counts[i] or 0)
                        j = i
                        while j < len(counts) and int(counts[j] or 0) == hc:
                            j += 1
                        if hc > 0:
                            new.append({"id": _uid("dm"), "role_id": role_id, "day": day,
                                        "start": start + i * slot, "end": start + j * slot,
                                        "headcount": hc, "source": "leader", "note": f"coverage grid ({day_type})"})
                        i = j
            d["demand"] = keep + new
        return ctx.mutate("card:coverage_grid", {"day_type": day_type, "days": days}, fn,
                          [f"demand for {day_type} (days {days})"], actor="leader")
    return CardRequest("coverage_grid", props, apply)


# --------------------------------------------------------------------------- #
# department_staffing (API.md v1.3): plain staffing per role -> DemandRequirements
# --------------------------------------------------------------------------- #
SUGGESTION_NOTE = ("Suggested starting point from your store hours and how many people are trained for each role. "
                   "Not a forecast, a corporate standard or a legal requirement. Edit freely.")


DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def day_groups(cfg: StoreConfig) -> list[dict]:
    """v1.5: groups from the store's actual open days: all, weekday, weekend (+ saturday/sunday), and
    each open day on its own. Groups with no open days are left out."""
    open_days = sorted({h.day for h in cfg.store.hours if h.close > h.open})
    groups = [("all", open_days), ("weekday", [d for d in open_days if d < 5]),
              ("weekend", [d for d in open_days if d >= 5]), ("saturday", [d for d in open_days if d == 5]),
              ("sunday", [d for d in open_days if d == 6])]
    groups += [(DAY_KEYS[d], [d]) for d in open_days]
    return [{"id": g, "days": days} for g, days in groups if days]


def group_days(group: str, open_days: list[int]) -> set[int]:
    """'all' | 'weekday' | 'weekend' | 'saturday' | 'sunday' | 'mon'..'sun' | comma list 'fri,sat'."""
    out: set[int] = set()
    for g in (x.strip().lower() for x in str(group or "").split(",")):
        if g == "all":
            out |= set(open_days)
        elif g == "weekday":
            out |= {d for d in open_days if d < 5}
        elif g == "weekend":
            out |= {d for d in open_days if d >= 5}
        elif g == "saturday":
            out.add(5)
        elif g == "sunday":
            out.add(6)
        elif g[:3] in DAY_KEYS:
            out.add(DAY_KEYS.index(g[:3]))
    return out & set(open_days)


def suggest_staffing(cfg: StoreConfig, role_ids: list[str]) -> tuple[dict, dict]:
    trained = {rid: sum(1 for e in cfg.employees if rid in e.trained_role_ids) for rid in role_ids}
    suggested = {rid: {"base": 0 if n < 2 else (2 if n >= 10 else 1), "peaks": [], "open": None, "close": None}
                 for rid, n in trained.items()}
    basis = {rid: f"{n} trained" for rid, n in trained.items()}
    return suggested, basis


def staffing_to_demand(cfg: StoreConfig, staffing: dict[str, dict]) -> list[dict]:
    """API.md: base across open hours per day; peaks replace base inside their windows; open/close crews in
    the pre-open/post-close windows. Times snap outward to the store's slots."""
    slot = cfg.store.slot_minutes
    open_days = sorted({h.day for h in cfg.store.hours if h.close > h.open})
    out: list[dict] = []
    for rid, st in staffing.items():
        for h in cfg.store.hours:
            if h.close <= h.open:
                continue
            hc: dict[int, int] = {}

            def paint(a: int, b: int, n: int, mode: str = "set") -> None:
                t = a - a % slot
                while t < b:
                    hc[t] = n if mode == "set" else max(hc.get(t, 0), n)
                    t += slot
            base = int(st.get("base") or 0)
            if base > 0:
                paint(h.open, h.close, base)
            for pk in st.get("peaks") or []:
                if h.day in group_days(pk.get("day_group", ""), open_days):
                    paint(int(pk["start"]), int(pk["end"]), int(pk["headcount"]))
            op, cl = st.get("open"), st.get("close")
            if op and int(op.get("headcount") or 0) > 0:
                paint(h.open - int(op.get("minutes_before_open") or 0), h.open, int(op["headcount"]), "max")
            if cl and int(cl.get("headcount") or 0) > 0:
                paint(h.close, h.close + int(cl.get("minutes_after_close") or 0), int(cl["headcount"]), "max")
            ts = sorted(t for t, n in hc.items() if n > 0)
            i = 0
            while i < len(ts):
                j = i
                while j + 1 < len(ts) and ts[j + 1] == ts[j] + slot and hc[ts[j + 1]] == hc[ts[i]]:
                    j += 1
                out.append({"id": _uid("dm"), "role_id": rid, "day": h.day, "start": max(0, ts[i]),
                            "end": ts[j] + slot, "headcount": hc[ts[i]], "source": "leader",
                            "note": "department staffing"})
                i = j + 1
    return out


def ask_department_staffing(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    cfg = ctx.config()
    dept = next((d for d in cfg.departments if d.id == args.get("department_id")), None)
    if dept is None:
        return ToolResult({"error": f"Unknown department_id {args.get('department_id')!r}",
                           "departments": [d.id for d in cfg.departments]})
    roles = [r for r in cfg.roles if r.department_id == dept.id]
    if not roles:
        return ToolResult({"error": f"Department {dept.id!r} has no roles yet; add roles first."})
    suggested, basis = suggest_staffing(cfg, [r.id for r in roles])
    stated = [rid for rid in (args.get("prefill") or {}) if rid in suggested]
    given = {k: str(v) for k, v in (args.get("rationale") or {}).items() if k in suggested}
    rationale = {rid: given.get(rid) or (f"A guess from what you told me; change it." if rid in stated else
                                        f"A starting guess from your hours and {basis[rid]}; change it.")
                 for rid in suggested}
    for rid in stated:  # what the leader already said in chat wins over the suggestion
        suggested[rid] = {**suggested[rid], **args["prefill"][rid]}
    props = {"department": dept.model_dump(mode="json"), "roles": [r.model_dump(mode="json") for r in roles],
             "day_groups": day_groups(cfg), "hours": [h.model_dump(mode="json") for h in cfg.store.hours],
             "pre_open_minutes": cfg.store.pre_open_minutes, "post_close_minutes": cfg.store.post_close_minutes,
             "suggested": suggested, "rationale": rationale, "suggestion_note": SUGGESTION_NOTE,
             "suggestion_basis": basis,
             "from_chat": stated}
    role_ids = {r.id for r in roles}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        staffing = {k: v for k, v in (result.get("staffing") or {}).items() if k in role_ids and isinstance(v, dict)}
        if not staffing:
            return ToolResult({"error": "No staffing for this department's roles in the result."})
        reqs = staffing_to_demand(ctx.config(), staffing)

        def fn(d):
            d["demand"] = [x for x in d["demand"] if not (x["role_id"] in staffing and x["source"] != "event")] + reqs
        res = ctx.mutate("card:department_staffing", {"department_id": dept.id, "staffing": staffing}, fn,
                         [f"demand for {dept.name}: {len(reqs)} blocks"], actor="leader")
        res.content["demand_blocks"] = len(reqs)
        return res
    return CardRequest("department_staffing", props, apply)


def show_coverage_preview(ctx: ToolContext, args: dict) -> CardRequest:
    """Read-only coverage_grid (props.readonly = true); does not wait for the leader."""
    card = ask_coverage_grid(ctx, args)
    card.props["readonly"] = True
    card.blocking = False
    card.apply = lambda result: ToolResult({"shown": True, "day_type": card.props["day_type"],
                                            "days": card.props["days"]})
    return card


SECTOR_EVENT_KINDS = {
    "food": ["delivery", "private_event", "catering", "promo", "other"],
    "retail": ["truck", "floor_set", "promo", "online_surge", "delivery"],
    "hospitality": ["private_event", "catering", "delivery", "promo", "other"],
}


def event_kinds(cfg: StoreConfig) -> list[str]:
    """v1.5: kinds relevant to the sector first; every kind stays valid."""
    sector = cfg.store.sector.value if cfg.store.sector else None
    first = SECTOR_EVENT_KINDS.get(sector, ["delivery", "private_event", "promo", "other"])
    return first + [k.value for k in EventKind if k.value not in first]


def ask_events(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    props = {"events": [e.model_dump(mode="json") for e in cfg.events], "kinds": event_kinds(cfg)}
    for ev in args.get("events") or []:
        ev.setdefault("id", _uid("ev"))
        _upsert(props["events"], ev)

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED

        def fn(d):
            d["events"] = result.get("events", [])
        return ctx.mutate("card:events", result, fn, [f"{len(result.get('events', []))} events"], actor="leader")
    return CardRequest("events", props, apply)


def ask_csv_import(ctx: ToolContext, args: dict) -> CardRequest:
    props = {"kind": args.get("kind", "roster")}

    def apply(result: dict) -> ToolResult:
        # The web commits through POST /import/{kind}/commit; this only reports back.
        return ToolResult({**result, "config_version": ctx.config().config_version})
    return CardRequest("csv_import", props, apply)


def propose_rule(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    raw = dict(args.get("constraint") or {})
    raw.setdefault("id", _uid("c"))
    raw.setdefault("status", "provisional")
    raw.setdefault("strength", "soft")
    raw.setdefault("source", "leader")
    try:
        constraint = Constraint.model_validate(raw)
    except ValidationError as e:
        return ToolResult({"error": "Invalid constraint", "details": _short_errors(e.errors(include_url=False))})
    props = {"constraint": constraint.model_dump(mode="json"), "evidence": args.get("evidence") or constraint.evidence or "",
             "plain_text": args.get("plain_text") or constraint.note}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        decision = result.get("decision")
        c = constraint.model_dump(mode="json")
        if decision == "not_a_rule":
            c["status"] = "rejected"
        elif decision in ("hard", "soft"):
            c["status"] = "confirmed"
            c["strength"] = decision
            if decision == "soft":
                w = result.get("weight_dollars")
                if not w or float(w) <= 0:
                    return ToolResult({"error": "A soft rule needs weight_dollars > 0; ask the leader what it is worth.",
                                       "decision": decision})
                c["weight_dollars"] = float(w)
        else:
            return ToolResult({"error": f"Unknown decision {decision!r}"})

        def fn(d):
            _upsert(d["constraints"], c)
        return ctx.mutate("card:propose_rule", {"constraint_id": c["id"], **result}, fn,
                          [f"rule {c['id']} ({c['kind']}) {c['status']}"], actor="leader")
    return CardRequest("propose_rule", props, apply)


def ask_tradeoff(ctx: ToolContext, args: dict) -> CardRequest:
    options = args.get("options") or []
    props = {"question": args.get("question", ""), "options": options}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        chosen = next((o for o in options if o.get("id") == result.get("option_id")), None)
        if chosen is None:
            return ToolResult({"error": f"option_id {result.get('option_id')!r} is not one of the offered options"})
        ctx.db.put(ctx.store_id, "tradeoff", chosen["id"], {"question": props["question"], "option": chosen})
        return ToolResult({"option_id": chosen["id"], "option": chosen})
    return CardRequest("tradeoff", props, apply)


def show_conflict_menu(ctx: ToolContext, args: dict) -> CardRequest:
    options = args.get("options") or []
    props = {"infeasibility": args.get("infeasibility") or {}, "options": options}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        chosen = next((o for o in options if o.get("id") == result.get("option_id")), None)
        if chosen is None:
            return ToolResult({"error": f"option_id {result.get('option_id')!r} is not one of the offered options"})
        ctx.db.put(ctx.store_id, "tradeoff", chosen["id"], {"question": "conflict_menu", "option": chosen})
        return ToolResult({"option_id": chosen["id"], "option": chosen,
                           "next": "Apply the chosen option with the matching mutation tool(s)."})
    return CardRequest("conflict_menu", props, apply)


def confirm_employee_availability(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    cfg = ctx.config()
    emp = next((e for e in cfg.employees if e.id == args.get("employee_id")), None)
    if emp is None:
        return ToolResult({"error": f"Unknown employee_id {args.get('employee_id')!r}"})
    props = {"employee": {"id": emp.id, "name": emp.name}, "parsed": args.get("parsed") or [],
             "original_text": args.get("original_text", "")}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        confirmed = result.get("confirmed") or []

        def fn(d):
            for e in d["employees"]:
                if e["id"] == emp.id:
                    e["availability"] = confirmed
        return ctx.mutate("card:employee_availability", {"employee_id": emp.id, "confirmed": confirmed}, fn,
                          [f"availability for {emp.name} ({len(confirmed)} entries)"], actor="leader")
    return CardRequest("employee_availability", props, apply)


# --------------------------------------------------------------------------- #
# Mutation tools
# --------------------------------------------------------------------------- #
def set_store_basics(ctx: ToolContext, args: dict) -> ToolResult:
    fields = {k: v for k, v in (args.get("fields") or args).items() if k != "id"}

    def fn(d):
        d["store"].update(fields)
    return ctx.mutate("set_store_basics", fields, fn, [f"store.{k}" for k in fields])


def set_budget(ctx: ToolContext, args: dict) -> ToolResult:
    fields = {k: args[k] for k in ("weekly_hours_cap", "weekly_dollar_cap", "overtime_allowed") if k in args}

    def fn(d):
        d["budget"].update(fields)
    return ctx.mutate("set_budget", fields, fn, [f"budget.{k}" for k in fields])


def upsert_role(ctx: ToolContext, args: dict) -> ToolResult:
    role = args.get("role") or {}
    dept = args.get("department")

    def fn(d):
        if dept:
            _upsert(d["departments"], dept)
        if not any(x["id"] == role.get("department_id") for x in d["departments"]):
            raise ToolError(f"department_id {role.get('department_id')!r} does not exist; pass `department` to add it.")
        if args.get("tags") is not None:
            d["role_tags"][role["id"]] = args["tags"]
        _upsert(d["roles"], role)
    return ctx.mutate("upsert_role", args, fn, [f"role {role.get('id')}"])


def upsert_employee(ctx: ToolContext, args: dict) -> ToolResult:
    emp = args.get("employee") or {}

    def fn(d):
        roles = {r["id"] for r in d["roles"]}
        bad = [r for r in emp.get("trained_role_ids", []) if r not in roles]
        if bad:
            raise ToolError(f"Unknown role ids {bad}; add the roles first.")
        _upsert(d["employees"], emp)
    return ctx.mutate("upsert_employee", {"employee_id": emp.get("id")}, fn, [f"employee {emp.get('id')}"])


def set_demand(ctx: ToolContext, args: dict) -> ToolResult:
    reqs = [dict(r) for r in args.get("requirements") or []]
    replace_days = args.get("replace_days")
    for r in reqs:
        r.setdefault("id", _uid("dm"))
        r.setdefault("source", "leader")

    def fn(d):
        roles = {r["id"] for r in d["roles"]}
        bad = sorted({r.get("role_id") for r in reqs if r.get("role_id") not in roles})
        if bad:
            raise ToolError(f"Unknown role ids {bad}")
        if replace_days is not None:
            d["demand"] = [x for x in d["demand"] if x["day"] not in replace_days]
        for r in reqs:
            _upsert(d["demand"], r)
    return ctx.mutate("set_demand", {"count": len(reqs), "replace_days": replace_days}, fn,
                      [f"{len(reqs)} demand requirements"])


def add_event(ctx: ToolContext, args: dict) -> ToolResult:
    ev = dict(args.get("event") or {})
    ev.setdefault("id", _uid("ev"))
    extra = [dict(r) for r in args.get("demand") or []]
    for r in extra:
        r.setdefault("id", _uid("dm"))
        r["source"] = "event"
        r["event_id"] = ev["id"]

    def fn(d):
        _upsert(d["events"], ev)
        for r in extra:
            _upsert(d["demand"], r)
    return ctx.mutate("add_event", ev, fn, [f"event {ev['id']} ({ev.get('kind')})"] + ([f"{len(extra)} event demand"] if extra else []))


def _check_constraint(c: dict) -> None:
    if c.get("source") == "law" and not c.get("citation"):
        raise ToolError("A law-sourced constraint needs a citation (from lookup_law).")
    if c.get("source") == "inferred":
        if not c.get("evidence"):
            raise ToolError("An inferred constraint needs evidence.")
        if c.get("status") == "confirmed":
            raise ToolError("Inferred rules stay provisional until the leader confirms them on a propose_rule card.")
    if c.get("strength") == "soft" and not (c.get("weight_dollars") or 0) > 0:
        raise ToolError("A soft constraint needs weight_dollars > 0. Ask the leader what it is worth.")


def add_constraint(ctx: ToolContext, args: dict) -> ToolResult:
    c = dict(args.get("constraint") or {})
    c.setdefault("id", _uid("c"))
    c.setdefault("status", "provisional")

    def fn(d):
        _check_constraint(c)
        _upsert(d["constraints"], c)
    return ctx.mutate("add_constraint", c, fn, [f"rule {c['id']} ({c.get('kind')}, {c.get('status')})"])


def set_constraint_status(ctx: ToolContext, args: dict) -> ToolResult:
    cid, status = args.get("constraint_id"), args.get("status")

    def fn(d):
        for c in d["constraints"]:
            if c["id"] == cid:
                if c.get("source") == "inferred" and status == "confirmed" and ctx.actor != "leader":
                    raise ToolError("Confirm inferred rules with a propose_rule card, not directly.")
                c["status"] = status
                return
        raise ToolError(f"No constraint with id {cid!r}")
    return ctx.mutate("set_constraint_status", args, fn, [f"rule {cid} -> {status}"])


def log_unmodeled(ctx: ToolContext, args: dict) -> ToolResult:
    note = {"id": _uid("u"), "text": args.get("text", ""), "reason": args.get("reason", ""),
            "created_at": datetime.now(timezone.utc).isoformat()}

    def fn(d):
        if not note["text"].strip():
            raise ToolError("text is required")
        d["unmodeled"].append(note)
    return ctx.mutate("log_unmodeled", note, fn, [f"unmodeled note {note['id']}"])


def approve_budget_increase(ctx: ToolContext, args: dict) -> ToolResult:
    option_id = args.get("option_id")
    choice = ctx.db.get(ctx.store_id, "tradeoff", option_id or "")
    if not choice:
        return ToolResult({"error": "No tradeoff card returned this option. Show an ask_tradeoff card with the "
                                    "dollar and hour cost first; only the leader's choice can raise the budget."})
    approval = {"id": _uid("ap"), "extra_hours": float(args.get("extra_hours") or 0),
                "extra_dollars": float(args.get("extra_dollars") or 0),
                "reason": args.get("reason") or choice["question"], "approved_by": "leader",
                "approved_at": datetime.now(timezone.utc).isoformat()}

    def fn(d):
        d["budget"]["approvals"].append(approval)
    res = ctx.mutate("approve_budget_increase", approval, fn,
                     [f"budget +{approval['extra_hours']:g}h / +${approval['extra_dollars']:g}"])
    if res.patch_summary:
        ctx.db.put(ctx.store_id, "tradeoff", option_id, {})  # one approval per choice
    return res


# --------------------------------------------------------------------------- #
# Read / compute tools
# --------------------------------------------------------------------------- #
def get_config_summary(ctx: ToolContext, args: dict) -> dict:
    cfg = ctx.config()
    return {
        "config_version": cfg.config_version,
        "store": cfg.store.model_dump(mode="json"),
        "departments": [d.model_dump(mode="json") for d in cfg.departments],
        "roles": [{"id": r.id, "name": r.name, "department_id": r.department_id,
                   "gap_penalty_per_hour": r.gap_penalty_per_hour, "min_age": r.min_age} for r in cfg.roles],
        "employees": [{"id": e.id, "name": e.name, "age": e.age, "status": e.status.value,
                       "trained_role_ids": e.trained_role_ids} for e in cfg.employees],
        "demand_count": len(cfg.demand),
        "demand_days": sorted({d.day for d in cfg.demand}),
        "events": [e.model_dump(mode="json") for e in cfg.events],
        "budget": cfg.budget.model_dump(mode="json"),
        "constraints": [c.model_dump(mode="json", exclude_none=True) for c in cfg.constraints],
        "unmodeled": [u.model_dump(mode="json") for u in cfg.unmodeled],
    }


def readiness_check(ctx: ToolContext, args: dict) -> dict:
    return readiness.compute(ctx.config(), equipment.state(ctx.db, ctx.store_id)).model_dump(mode="json")


def review_equipment_role(ctx: ToolContext, args: dict) -> ToolResult:
    """Only after the leader said so: confirm keeps the powered_industrial_truck tag, reject removes it."""
    try:
        cfg = equipment.decide(ctx.db, ctx.store_id, args.get("role_id", ""), args.get("decision", ""))
    except KeyError:
        return ToolResult({"error": f"Unknown role_id {args.get('role_id')!r}"})
    except ValueError as e:
        return ToolResult({"error": str(e)})
    summary = [f"equipment role {args['role_id']} {args['decision']}ed"]
    return ToolResult({"ok": True, "config_version": cfg.config_version, "changed": summary},
                      patch_summary=summary, config_version=cfg.config_version)


def with_law(cfg: StoreConfig) -> StoreConfig:
    cfg = cfg.model_copy(deep=True)
    cfg.law_pack = integrations.resolve_law(cfg.store.jurisdiction)
    return cfg


async def dry_run_solve(ctx: ToolContext, args: dict) -> dict:
    cfg = with_law(ctx.config())
    t = float(args.get("time_limit_s") or 10)
    sched = await asyncio.to_thread(integrations.solve_week, cfg, t)
    try:
        val = await asyncio.to_thread(integrations.validate, cfg, sched)
        validation = {"passed": val.passed, "hard_count": val.hard_count,
                      "hard_violations": [v.model_dump(mode="json", exclude_none=True)
                                          for v in val.violations if v.severity == "hard"][:10]}
    except integrations.StubUnavailable as e:
        validation = {"unavailable": str(e)}
    gaps = sorted(sched.gaps, key=lambda g: -g.penalty_dollars)
    return {
        "produced_by": sched.produced_by,
        "status": sched.status,
        "metrics": sched.metrics.model_dump(mode="json") if sched.metrics else None,
        "infeasibility": sched.infeasibility.model_dump(mode="json") if sched.infeasibility else None,
        "gap_count": len(gaps),
        "top_gaps": [g.model_dump(mode="json") for g in gaps[:10]],
        "validation": validation,
        "law_warnings": cfg.law_pack.warnings if cfg.law_pack else [],
    }


def explain_gap_tool(ctx: ToolContext, args: dict) -> dict:
    cfg = ctx.config()
    try:
        sched, _ = ctx.db.latest_schedule(ctx.store_id)
    except KeyError:
        return {"error": "No schedule yet. Solve first."}
    gap = next((g for g in sched.gaps if g.role_id == args.get("role_id") and g.day == args.get("day")
                and g.start <= int(args.get("start", -1)) < g.end), None)
    if gap is None:
        return {"error": "No gap in the latest schedule matches that role/day/time."}
    reasons = integrations.explain_gap(cfg, sched, gap)
    names = {e.id: e.name for e in cfg.employees}
    return {"gap": gap.model_dump(mode="json", exclude={"reasons"}),
            "reasons": [{**r.model_dump(mode="json", exclude_none=True), "employee_name": names.get(r.employee_id)}
                        for r in reasons],
            "note": "Only these engine reasons may be stated. Do not add others."}


def lookup_law(ctx: ToolContext, args: dict) -> dict:
    cfg = ctx.config()
    j = Jurisdiction(state=(args.get("state") or cfg.store.jurisdiction.state).upper(),
                     city=(args.get("city") or (cfg.store.jurisdiction.city if not args.get("state") else None)))
    pack = integrations.resolve_law(j)
    rt = args.get("rule_type")
    rules = [r for r in pack.rules if not rt or r.type.value == rt]
    return {
        "jurisdiction": j.model_dump(mode="json"),
        "coverage": pack.coverage,
        "warnings": pack.warnings,
        "rules": [{"id": r.id, "level": r.level, "type": r.type.value, "summary": r.summary, "params": r.params,
                   "confidence": r.confidence, "verified": r.verified,
                   "citation": {"title": r.citation.title, "url": r.citation.url}} for r in rules],
        "note": ("Answer ONLY from these rules, citing each. If the list is empty, say the dataset has no entry and "
                 "that this is not legal advice."),
    }


def mine_patterns_tool(ctx: ToolContext, args: dict) -> dict:
    cfg = ctx.config()
    found = integrations.mine_patterns(cfg, [])
    return {"proposed": [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in found],
            "note": "Propose each with a propose_rule card; they are provisional until confirmed."}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_EVENT_KIND = [k.value for k in EventKind]

TOOLS: list[Tool] = [
    # cards
    Tool("ask_store_basics", "Show the store_basics card (name, location, hours, slot size, week start). "
         "Pauses until the leader submits; the result is saved to the config.", PREFILL, ask_store_basics, "card"),
    Tool("ask_payroll", "Show the payroll card (weekly hours cap, optional dollar cap, overtime allowed). "
         "Saved on submit.", PREFILL, ask_payroll, "card"),
    Tool("ask_roles", "Show the roles card (departments and roles, each with gap_penalty_per_hour). Pass proposed "
         "departments/roles to prefill. Saved on submit.",
         _obj({"departments": {"type": "array", "items": {"type": "object"}},
               "roles": {"type": "array", "items": {"type": "object"}}}), ask_roles, "card"),
    Tool("ask_training_matrix", "Show the training matrix card (employee x role). Saved on submit.",
         _obj({}), ask_training_matrix, "card"),
    Tool("ask_coverage_grid", "ADVANCED editor, only when the leader asks to edit the grid directly. "
         "Show the coverage grid card for one day type (headcount per role per slot). "
         "One set of numbers applies to every listed day, and submitting replaces leader demand on those days. "
         "The grid widens to cover events on those days (e.g. an early delivery). Use day_type 'custom' with "
         "`days` for any set of days.",
         _obj({"day_type": {"type": "string", "enum": sorted(DAY_TYPES)},
               "days": {"type": "array", "items": {"type": "integer"}, "description": "Override which days (0=Mon)."}},
              ["day_type"]), ask_coverage_grid, "card"),
    Tool("ask_department_staffing", "Default way to set demand: one card per department with plain staffing per role "
         "(base people all day, peaks per day group, open/close crews), prefilled with labeled suggestions. Pass "
         "`prefill` {role_id: RoleStaffing} with anything the leader already said in chat (e.g. 4 cashiers 5-8 pm "
         "weekdays -> peaks:[{day_group:'weekday',start:1020,end:1200,headcount:4}]). Saved as demand on submit.",
         _obj({"department_id": {"type": "string"}, "prefill": {"type": "object"},
               "rationale": {"type": "object", "description": "{role_id: one sentence on what the guess is based "
                                                               "on, quoting the leader}"}}, ["department_id"]),
         ask_department_staffing, "card"),
    Tool("show_coverage_preview", "Show a read-only coverage grid for a day type so the leader can see the demand "
         "that was saved (does not wait for input).",
         _obj({"day_type": {"type": "string", "enum": sorted(DAY_TYPES)},
               "days": {"type": "array", "items": {"type": "integer"}}}, ["day_type"]), show_coverage_preview, "card"),
    Tool("ask_events", "Show the events card (e.g. deliveries, private events, catering, promos; trucks and floor "
         "sets for retail). Kinds are ordered for the business's sector. Saved on submit.",
         _obj({"events": {"type": "array", "items": {"type": "object"}}}), ask_events, "card"),
    Tool("ask_csv_import", "Show the CSV import card for a kind of export the leader has.",
         _obj({"kind": {"type": "string", "enum": ["roster", "training", "availability", "forecast", "history",
                                                    "labor_model", "labor_hours", "labor_standards",
                                                    "sales_forecast", "workload"]}},
              ["kind"]), ask_csv_import, "card"),
    Tool("propose_rule", "Show a rule card so the leader decides hard / soft (and $ weight) / not a rule. "
         "Use for every unwritten rule and every mined pattern.",
         _obj({"constraint": {"type": "object", "description": "A Constraint (kind must be a ConstraintKind)."},
               "evidence": {"type": "string"}, "plain_text": {"type": "string"}}, ["constraint", "plain_text"]),
         propose_rule, "card"),
    Tool("ask_tradeoff", "Show priced options and let the leader choose. Required before approve_budget_increase. "
         "Every cost must come from a tool result.",
         _obj({"question": {"type": "string"},
               "options": {"type": "array", "items": _obj({"id": {"type": "string"}, "label": {"type": "string"},
                                                            "cost_dollars": {"type": "number"},
                                                            "effect": {"type": "string"}}, ["id", "label"])}},
              ["question", "options"]), ask_tradeoff, "card"),
    Tool("show_conflict_menu", "When hard rules conflict (infeasibility), show the conflicting rules with priced options.",
         _obj({"infeasibility": {"type": "object"},
               "options": {"type": "array", "items": _obj({"id": {"type": "string"}, "label": {"type": "string"},
                                                            "cost_dollars": {"type": "number"},
                                                            "patch_summary": {"type": "string"}}, ["id", "label"])}},
              ["infeasibility", "options"]), show_conflict_menu, "card"),
    Tool("confirm_employee_availability", "Show parsed availability for one employee to confirm. Saved on submit.",
         _obj({"employee_id": {"type": "string"}, "parsed": {"type": "array", "items": {"type": "object"}},
               "original_text": {"type": "string"}}, ["employee_id", "parsed"]),
         confirm_employee_availability, "card"),
    # mutations
    Tool("set_store_basics", "Update Store fields (name, jurisdiction, timezone, slot_minutes, week_start, hours...).",
         _obj({"fields": {"type": "object"}}, ["fields"]), set_store_basics, "mutation"),
    Tool("set_budget", "Set the weekly hours cap, optional dollar cap, and whether overtime is allowed.",
         _obj({"weekly_hours_cap": {"type": "number"}, "weekly_dollar_cap": {"type": ["number", "null"]},
               "overtime_allowed": {"type": "boolean"}}), set_budget, "mutation"),
    Tool("upsert_role", "Add or update a role. Pass `department` to add its department too, `tags` for role tags.",
         _obj({"role": {**_schema(Role)}, "department": {"type": "object"},
               "tags": {"type": "array", "items": {"type": "string"}}}, ["role"]), upsert_role, "mutation"),
    Tool("upsert_employee", "Add or update an employee (trained roles must exist).",
         _obj({"employee": {"type": "object", "description": "An Employee (see contracts)."}}, ["employee"]),
         upsert_employee, "mutation"),
    Tool("set_demand", "Add/update DemandRequirements. `replace_days` first clears those days.",
         _obj({"requirements": {"type": "array", "items": {"type": "object"}},
               "replace_days": {"type": "array", "items": {"type": "integer"}}}, ["requirements"]),
         set_demand, "mutation"),
    Tool("add_event", "Add an event (any EventKind, with a `label`) and any demand it adds.",
         _obj({"event": _obj({"kind": {"type": "string", "enum": _EVENT_KIND}, "day": {"type": "integer"},
                              "start": {"type": "integer"}, "end": {"type": "integer"}, "note": {"type": "string"}},
                             ["kind", "day", "start", "end"]),
               "demand": {"type": "array", "items": {"type": "object"}}}, ["event"]), add_event, "mutation"),
    Tool("add_constraint", "Add a Constraint. Prefer propose_rule so the leader decides hard/soft and weight.",
         _obj({"constraint": {"type": "object"}}, ["constraint"]), add_constraint, "mutation"),
    Tool("set_constraint_status", "Set a constraint's status (provisional|confirmed|rejected).",
         _obj({"constraint_id": {"type": "string"},
               "status": {"type": "string", "enum": [s.value for s in RuleStatus]}}, ["constraint_id", "status"]),
         set_constraint_status, "mutation"),
    Tool("log_unmodeled", "Record something the leader said that no ConstraintKind can express. Say so in one sentence.",
         _obj({"text": {"type": "string"}, "reason": {"type": "string"}}, ["text", "reason"]), log_unmodeled, "mutation"),
    Tool("approve_budget_increase", "Raise the budget ONLY after an ask_tradeoff card returned this option_id.",
         _obj({"option_id": {"type": "string"}, "extra_hours": {"type": "number"}, "extra_dollars": {"type": "number"},
               "reason": {"type": "string"}}, ["option_id"]), approve_budget_increase, "mutation"),
    # reads / computes
    Tool("get_config_summary", "Read the current store config.", _obj({}), get_config_summary),
    Tool("review_equipment_role", "After the LEADER decides: confirm (keep) or reject (remove) the automatic "
         "powered_industrial_truck tag on a role. Never decide this yourself.",
         _obj({"role_id": {"type": "string"}, "decision": {"type": "string", "enum": ["confirm", "reject"]}},
              ["role_id", "decision"]), review_equipment_role, "mutation"),
    Tool("readiness_check", "Check whether the store is ready to schedule; lists what's missing.", _obj({}),
         readiness_check),
    Tool("dry_run_solve", "Run the engine and validator on the current config. Returns metrics, gaps, infeasibility. "
         "Every number you state must come from here.", _obj({"time_limit_s": {"type": "number"}}), dry_run_solve),
    Tool("explain_gap", "Engine reasons why a gap in the latest schedule is uncovered.",
         _obj({"role_id": {"type": "string"}, "day": {"type": "integer"}, "start": {"type": "integer"}},
              ["role_id", "day", "start"]), explain_gap_tool),
    Tool("lookup_law", "Look up labor law from the cited dataset. The ONLY allowed source for any legal statement.",
         _obj({"state": {"type": "string"}, "city": {"type": "string"},
               "rule_type": {"type": "string", "enum": [t.value for t in LawRuleType]}}), lookup_law),
    Tool("mine_patterns", "Find patterns in past schedules that could become rules (provisional until confirmed).",
         _obj({}), mine_patterns_tool),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
MODE_TOOLS = {
    "onboard": [t.name for t in TOOLS],
    "review": [t.name for t in TOOLS],
    "fix": [t.name for t in TOOLS],
}


def specs_for(mode: str) -> list[dict]:
    return [TOOLS_BY_NAME[n].spec() for n in MODE_TOOLS.get(mode, MODE_TOOLS["onboard"])]
