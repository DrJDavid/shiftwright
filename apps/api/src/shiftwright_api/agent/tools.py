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
import math
import re
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
    Employee,
    Role,
    RuleStatus,
    StoreConfig,
)

from .. import equipment, import_flow, integrations, priorities, readiness, tradeoffs, rules
from ..imports import AUTO_PRIORITY
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
        levels = priorities.load(self.db, self.store_id)
        unpriced = fn

        def fn(d):  # noqa: F811 - same mutation, then reprice leveled roles from current wages
            out = unpriced(d)
            priorities.apply(out if out is not None else d, levels)
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
            status = equipment.record_auto(self.db, self.store_id, tagged)
            summary = summary + [f"tagged: {equipment.describe(tagged)}"]
            unclear = [t for t in tagged if status.get(t[0]) == "auto"]
            clear = [t for t in tagged if status.get(t[0]) == "clear"]
            notes = []
            if clear:
                notes.append(f"Clearly hazard/equipment work by name, tags kept: {equipment.describe(clear)}. Mention it "
                             "in one short clause (minor-labor rules in the law dataset will apply; they can remove a "
                             "tag on Team & rules). Don't ask about these.")
            if unclear:
                notes.append(f"Unsure from the name: {equipment.describe(unclear)}. Ask the owner to keep or remove "
                             "these on the confirm_tags card (ask_confirm_tags), once, after roles are set up.")
            content.update(changed=summary, equipment_tagged={rid: tags for rid, _, tags in tagged},
                           equipment_status=status, note=" ".join(notes))
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
        _drop_closed(fields)

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


def _proposed_level(item: dict) -> Optional[str]:
    """Level for a role the agent proposes: the one it names, else the default unless a $ priority was stated."""
    if item.get("priority") in priorities.LEVELS:
        return item["priority"]
    stated = item.get("gap_penalty_per_hour")
    return None if stated and float(stated) > 0 else priorities.DEFAULT_LEVEL


def ask_roles(ctx: ToolContext, args: dict) -> CardRequest:
    cfg = ctx.config()
    levels = priorities.load(ctx.db, ctx.store_id)
    props = {"departments": [d.model_dump(mode="json") for d in cfg.departments],
             "roles": [{**r.model_dump(mode="json"),
                        "priority": levels.get(r.id) or ("important" if AUTO_PRIORITY in r.description else None)}
                       for r in cfg.roles]}
    for key in ("departments", "roles"):
        for item in args.get(key) or []:
            if key == "roles":
                existing = next((r for r in props["roles"] if r["id"] == item.get("id")), None)
                lvl = _proposed_level(item) if existing is None or item.get("priority") else existing["priority"]
                item = {**item, "priority": lvl}
                if lvl:
                    item["gap_penalty_per_hour"] = priorities.penalty(lvl)
            _upsert(props[key], item)

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        new_levels = dict(levels)
        roles_out = []
        for r in result.get("roles") or []:
            r = dict(r)
            lvl = r.pop("priority", None)
            if lvl in priorities.LEVELS:
                new_levels[r["id"]] = lvl
                # the leader chose: stop treating it as an automatically priced import
                r["description"] = (r.get("description") or "").replace(f"({AUTO_PRIORITY}); ", "").replace(
                    f"({AUTO_PRIORITY})", "")
            else:
                new_levels.pop(r.get("id"), None)  # custom $ priority from the card
            roles_out.append(r)
        if result.get("roles") is not None:
            result = {**result, "roles": roles_out}
            priorities.save(ctx.db, ctx.store_id, new_levels)

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
    kind = args.get("kind", "roster")
    props: dict = {"kind": kind}
    cached = import_flow.cached_preview(ctx.db, ctx.store_id, kind)
    if cached:
        props["preview"] = cached

    def apply(result: dict) -> ToolResult:
        if "mapping" in result and not result.get("committed") and not _cancelled(result):
            # Result {mapping}: commit the cached upload with that mapping here (attached files, headless).
            try:
                cfg, warnings = import_flow.commit(ctx.db, ctx.store_id, kind, result.get("mapping") or {})
            except import_flow.CommitError as e:
                return ToolResult({"error": f"Import not committed: {e.detail}"})
            rows = len(ctx.db.get(ctx.store_id, "import_rows", kind) or [])
            summary = [f"imported {kind}: {rows} rows"]
            return ToolResult({"committed": True, "rows": rows, "config_version": cfg.config_version,
                               "warnings": warnings[:15], "warning_count": len(warnings), "changed": summary},
                              patch_summary=summary, config_version=cfg.config_version)
        # The web commits through POST /import/{kind}/commit and reports {committed, rows}.
        return ToolResult({**result, "config_version": ctx.config().config_version})
    return CardRequest("csv_import", props, apply)


DEFAULT_SOFT_WEIGHT = rules.STRENGTHS["preference"][2]  # tier value; never ask the leader for dollars


def _person_id(cfg: StoreConfig, ref: str) -> str:
    """An employee id from how the leader names them: an id, a full name, a first name, or "Jules C."
    Returns the ref unchanged if it isn't one unique person (the contract check then reports it)."""
    ref = (ref or "").strip()
    if any(e.id == ref for e in cfg.employees):
        return ref
    words = [w for w in re.split(r"[\s.]+", ref.lower()) if w]
    if not words:
        return ref

    def fits(name: str) -> bool:
        parts = [w for w in re.split(r"[\s.]+", name.lower()) if w]
        if not parts or parts[0] != words[0]:
            return False
        rest = words[1:]
        return all(any(p.startswith(w) for p in parts[1:]) for w in rest)

    hits = [e.id for e in cfg.employees if fits(e.name)]
    return hits[0] if len(hits) == 1 else ref


def _resolve_people(cfg: StoreConfig, raw: dict) -> dict:
    p = dict(raw.get("params") or {})
    if "employee_ids" in p:
        p["employee_ids"] = [_person_id(cfg, x) for x in p["employee_ids"]]
    if "employee_id" in p:
        p["employee_id"] = _person_id(cfg, p["employee_id"])
    out = {**raw, "params": p}
    if raw.get("applies_to_employee_ids"):
        out["applies_to_employee_ids"] = [_person_id(cfg, x) for x in raw["applies_to_employee_ids"]]
    return out


def propose_rule(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    raw = _resolve_people(ctx.config(), dict(args.get("constraint") or {}))
    raw.setdefault("id", _uid("c"))
    raw.setdefault("status", "provisional")
    raw.setdefault("strength", "soft")
    raw.setdefault("source", "leader")
    level = args.get("level") if args.get("level") in rules.STRENGTHS else rules.level_of(
        raw.get("strength"), raw.get("weight_dollars"))
    rules.set_level(raw, level)
    why = rules.problem(raw.get("kind", ""), raw.get("params"))
    if why:
        return ToolResult({"error": f"Rule not shown: {why}. Fill in the params from what the leader said "
                                    "and call propose_rule again."})
    try:
        constraint = Constraint.model_validate(raw)
    except ValidationError as e:
        return ToolResult({"error": "Invalid constraint", "details": _short_errors(e.errors(include_url=False))})
    props = {"constraint": constraint.model_dump(mode="json"), "evidence": args.get("evidence") or constraint.evidence or "",
             "plain_text": args.get("plain_text") or constraint.note,
             "level": level, "levels": rules.STRENGTH_CHOICES}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        decision = result.get("decision")
        if decision in ("hard", "soft"):  # older clients: firm rule / preference (+ optional weight → its tier)
            decision = rules.level_of(decision, result.get("weight_dollars"))
        c = constraint.model_dump(mode="json")
        if decision == rules.NOT_A_RULE[0]:
            c["status"] = "rejected"
        elif decision in rules.STRENGTHS:
            c["status"] = "confirmed"
            rules.set_level(c, decision)
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


def get_tradeoffs(ctx: ToolContext, args: dict) -> dict:
    """The latest build's tradeoffs (biggest first), each with the plain question its card will ask."""
    items = tradeoffs.latest(ctx.db, ctx.store_id)
    done = tradeoffs.answered(ctx.db, ctx.store_id)
    out = tradeoffs.summaries(ctx.config(), items, done)
    return {"tradeoffs": out, "next": "Call ask_build_tradeoff for each unanswered one, in this order, one at a time."
            if any(not t["answered"] for t in out) else "Nothing left to decide from the last build."}


def ask_build_tradeoff(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    """`tradeoff` card for one of the latest build's tradeoffs, worded from the solve's real numbers. The
    leader's answer applies it: approve → budget approval (+hours); drop → the rule is rejected."""
    tid = args.get("tradeoff_id")
    t = next((x for x in tradeoffs.latest(ctx.db, ctx.store_id) if x["id"] == tid), None)
    if t is None:
        return ToolResult({"error": f"No tradeoff {tid!r} in the latest build; call get_tradeoffs."})
    if tid in tradeoffs.answered(ctx.db, ctx.store_id):
        return ToolResult({"error": f"The leader already answered {tid!r}; move on to the next one."})
    cfg = ctx.config()
    props = tradeoffs.card(cfg, t)

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        return decide_build_tradeoff(ctx.db, ctx.store_id, tid, str(result.get("option_id") or ""))
    return CardRequest("tradeoff", props, apply)


def decide_build_tradeoff(db: Database, store_id: str, tid: str, option_id: str) -> ToolResult:
    """The leader's answer to one build tradeoff (from the chat card or the Decisions panel): approve →
    budget approval (+hours); drop → the rule is rejected; leave_open / keep → recorded only."""
    t = next((x for x in tradeoffs.latest(db, store_id) if x["id"] == tid), None)
    if t is None:
        return ToolResult({"error": f"No tradeoff {tid!r} in the latest build."})
    if tid in tradeoffs.answered(db, store_id):
        return ToolResult({"error": f"Already decided: {tid!r}."})
    cfg = db.get_config(store_id)
    props = tradeoffs.card(cfg, t)
    chosen = next((o for o in props["options"] if o["id"] == option_id), None)
    if chosen is None:
        return ToolResult({"error": f"option_id {option_id!r} is not one of the offered options"})
    db.put(store_id, "tradeoff", chosen["id"], {"question": props["question"], "option": chosen})
    choice = chosen["id"].rsplit(":", 1)[1]
    tradeoffs.mark_answered(db, store_id, tid, choice)
    leader = ToolContext(db=db, store_id=store_id, actor="leader")
    out: Optional[ToolResult] = None
    if choice == "approve":
        extra = float(t.get("extra_hours") or 0)
        dollars = math.ceil(chosen["cost_dollars"]) if cfg.budget.weekly_dollar_cap else 0
        out = approve_budget_increase(leader, {"option_id": chosen["id"], "extra_hours": extra,
                                               "extra_dollars": dollars, "reason": props["question"]})
    elif choice == "drop":
        rid = t.get("rule_id")

        def fn(d):
            for c in d["constraints"]:
                if c["id"] == rid:
                    c["status"] = "rejected"
        out = leader.mutate("card:tradeoff", {"tradeoff_id": tid, "rule_id": rid, "status": "rejected"}, fn,
                            [f"rule {rid} dropped"])
    content = {"tradeoff_id": tid, "option_id": chosen["id"], "decision": choice, "option": chosen}
    if out is None:
        return ToolResult(content)
    if "error" in out.content:
        return ToolResult({**content, **out.content})
    content["next"] = "Applies from the next build (dry_run_solve, or the leader's Build button)."
    return ToolResult({**out.content, **content}, patch_summary=out.patch_summary,
                      config_version=out.config_version)


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
def _drop_closed(fields: dict) -> None:
    """A closed day is simply absent from Store.hours (the model sometimes sends {day, closed: true})."""
    if isinstance(fields.get("hours"), list):
        fields["hours"] = [h for h in fields["hours"] if isinstance(h, dict) and not h.get("closed")
                           and "open" in h and "close" in h]


def set_store_basics(ctx: ToolContext, args: dict) -> ToolResult:
    fields = {k: v for k, v in (args.get("fields") or args).items() if k != "id"}
    _drop_closed(fields)

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
    role = {k: v for k, v in role.items() if k != "priority"}
    levels = priorities.load(ctx.db, ctx.store_id)
    is_new = not any(r.id == role.get("id") for r in ctx.config().roles)
    lvl = args.get("priority") if args.get("priority") in priorities.LEVELS else (
        _proposed_level(role) if is_new else levels.get(role.get("id")))
    if lvl:
        levels[role["id"]] = lvl
        role.setdefault("gap_penalty_per_hour", 0.0)  # set to the level's tier value by the mutate hook
        priorities.save(ctx.db, ctx.store_id, levels)

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
    emp = dict(args.get("employee") or {})

    def fn(d):
        roles = {r["id"]: r for r in d["roles"]}
        bad = [r for r in emp.get("trained_role_ids", []) if r not in roles]
        if bad:
            raise ToolError(f"Unknown role ids {bad}; add the roles first.")
        old = next((e for e in d["employees"] if e["id"] == emp.get("id")), {})
        merged = {**old, **emp}
        # chat-entered people: fill structural defaults the leader wasn't asked about (never wages/ages)
        trained = merged.get("trained_role_ids") or []
        merged.setdefault("trained_role_ids", trained)
        if not merged.get("home_department_id") and trained:
            merged["home_department_id"] = roles[trained[0]]["department_id"]
        merged.setdefault("status", "part_time")
        merged.setdefault("hire_date", d["store"]["week_start"])
        merged.setdefault("phone", "")  # optional: only needed to text them about open shifts
        if merged.get("phone"):
            from ..imports import parse_phone
            merged["phone"] = parse_phone(str(merged["phone"])) or merged["phone"]
        _upsert(d["employees"], merged)
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
    why = rules.problem(c.get("kind", ""), c.get("params"))
    if why:
        raise ToolError(f"Rule not saved: {why}. Fill in the params from what the leader said and try again.")
    if c.get("strength") != "hard":  # a preference: its weight is a tier from the strength word, never dollars
        rules.set_level(c, rules.level_of(c.get("strength") or "soft", c.get("weight_dollars")))


def add_constraint(ctx: ToolContext, args: dict) -> ToolResult:
    c = dict(args.get("constraint") or {})
    c.setdefault("id", _uid("c"))
    if ctx.actor != "leader":  # strength/confirmation are the leader's call: only via a propose_rule card
        c["status"] = "provisional"

    def fn(d):
        _check_constraint(c)
        _upsert(d["constraints"], c)
    return ctx.mutate("add_constraint", c, fn, [f"rule {c['id']} ({c.get('kind')}, {c.get('status')})"])


def set_constraint_status(ctx: ToolContext, args: dict) -> ToolResult:
    cid, status = args.get("constraint_id"), args.get("status")

    def fn(d):
        for c in d["constraints"]:
            if c["id"] == cid:
                if status == "confirmed" and ctx.actor != "leader":
                    raise ToolError("Only the leader confirms a rule: show it with propose_rule and let them decide.")
                if status == "rejected" and ctx.actor != "leader" and c.get("status") != "provisional":
                    raise ToolError("This rule was decided by the leader; ask them before changing it.")
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


def ask_confirm_tags(ctx: ToolContext, args: dict) -> Union[CardRequest, ToolResult]:
    """`confirm_tags` card: every role with automatic hazard/equipment tags, Keep/Remove per role. The owner's
    submission is the only way these get confirmed or removed (the agent can't record it)."""
    cfg = ctx.config()
    review = equipment.state(ctx.db, ctx.store_id)
    names = {r.id: r.name for r in cfg.roles}
    pending = [rid for rid, v in review.items() if v.get("status") == "auto" and rid in names]
    if not pending:
        return ToolResult({"ok": True, "note": "No tags waiting for the owner."})
    props = {"roles": [{"role_id": rid, "name": names[rid], "tags": review[rid].get("tags") or [],
                        "minors_trained": [f"{e.name} ({e.age})" for e in cfg.employees
                                           if e.age < 18 and rid in e.trained_role_ids]} for rid in pending],
             "note": "Tags let the law dataset's minor-labor rules apply to these roles. Keep or remove each."}

    def apply(result: dict) -> ToolResult:
        if _cancelled(result):
            return CANCELLED
        decisions = result.get("decisions") or {}
        done, version = {}, cfg.config_version
        for rid in pending:
            d = decisions.get(rid)
            if d not in ("keep", "remove"):
                continue
            version = equipment.decide(ctx.db, ctx.store_id, rid, "confirm" if d == "keep" else "reject").config_version
            done[rid] = d
        left = [rid for rid in pending if rid not in done]
        summary = [f"tags {d}: {names[r]}" for r, d in done.items()]
        return ToolResult({"ok": True, "decisions": done, "still_pending": left, "config_version": version},
                          patch_summary=summary or None, config_version=version if done else None)
    return CardRequest("confirm_tags", props, apply)


def with_law(cfg: StoreConfig) -> StoreConfig:
    cfg = cfg.model_copy(deep=True)
    cfg.law_pack = integrations.resolve_law(cfg.store.jurisdiction)
    return cfg


async def dry_run_solve(ctx: ToolContext, args: dict) -> dict:
    cfg = with_law(ctx.config())
    t = float(args["time_limit_s"]) if args.get("time_limit_s") else None  # None: until it stops improving
    sched = await asyncio.to_thread(integrations.solve_week, cfg, t)
    try:
        val = await asyncio.to_thread(integrations.validate, cfg, sched)
        validation = {"passed": val.passed, "hard_count": val.hard_count,
                      "hard_violations": [v.model_dump(mode="json", exclude_none=True)
                                          for v in val.violations if v.severity == "hard"][:10]}
    except integrations.StubUnavailable as e:
        validation = {"unavailable": str(e)}
    gaps = sorted(sched.gaps, key=lambda g: -g.penalty_dollars)
    found = tradeoffs.save(ctx.db, ctx.store_id, sched)
    return {
        "tradeoffs": tradeoffs.summaries(cfg, found),
        "next": ("Ask the leader about each tradeoff with ask_build_tradeoff, biggest first, one card at a time."
                 if found else None),
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
    Tool("ask_roles", "Show the roles card (departments and roles). Each role has a `priority`: must_cover | "
         "important | nice_to_have (default important); the tool prices it from the pay of the people trained for "
         "it, so every level is worth covering and lower levels go uncovered first when hours or people run out. "
         "Pass a role's priority only if the leader said it; never pass gap_penalty_per_hour unless they gave a "
         "dollar value. Saved on submit.",
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
    Tool("propose_rule", "Show a rule card so the leader picks Firm rule, Strong preference, Preference or Not a "
         "rule. Use for every unwritten rule and every mined pattern. Set `level` yourself from their words: "
         "absolutes (never, nobody, always, can't, no more than, at least) are firm; 'really try to', 'whenever "
         "possible' are strong_preference; 'prefer', 'try to', 'when you can' are preference. Never put dollars "
         "on a rule. People may be named as the leader names them (id, full name, 'Jules C.'); the tool "
         "matches them to the roster.",
         _obj({"constraint": {"type": "object", "description": "A Constraint (kind must be a ConstraintKind); "
                                                                  "strength and weight come from `level`."},
               "level": {"type": "string", "enum": list(rules.STRENGTHS)},
               "evidence": {"type": "string"}, "plain_text": {"type": "string"}}, ["constraint", "plain_text"]),
         propose_rule, "card"),
    Tool("get_tradeoffs", "The latest build's tradeoffs (budget gaps and costly preferences), biggest first, each with "
         "the question its card asks. Call after the leader builds the week outside chat.", _obj({}), get_tradeoffs),
    Tool("ask_build_tradeoff", "Show the tradeoff card for one tradeoff from the latest build (from dry_run_solve or "
         "get_tradeoffs). The server writes the question and options from the solve's numbers and applies the "
         "leader's answer (approve hours / leave open; keep / drop the rule). One at a time, biggest first.",
         _obj({"tradeoff_id": {"type": "string"}}, ["tradeoff_id"]), ask_build_tradeoff, "card"),
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
    Tool("upsert_role", "Add or update a role. Pass `department` to add its department too, `tags` for role tags, "
         "`priority` (must_cover | important | nice_to_have) only if the leader said it; new roles default to "
         "important. Never pass gap_penalty_per_hour unless the leader gave a dollar value.",
         _obj({"role": {**_schema(Role), "required": ["id", "department_id", "name"]}, "department": {"type": "object"},
               "priority": {"type": "string", "enum": list(priorities.LEVELS)},
               "tags": {"type": "array", "items": {"type": "string"}}}, ["role"]), upsert_role, "mutation"),
    Tool("upsert_employee", "Add or update one employee (trained roles must exist). Required: id, name, age, "
         "wage_per_hour, trained_role_ids. phone is optional (only needed to text them about open shifts; "
         "don't ask for it during setup, never invent one). hire_date defaults to the schedule week, "
         "home_department_id to the first role's department, status to part_time. "
         "tipped_wage_per_hour only if the leader states a tipped cash wage.",
         _obj({"employee": {**_schema(Employee),
                            # the tool fills phone/hire_date/home_department_id/status itself
                            "required": ["id", "name", "age", "wage_per_hour", "trained_role_ids"]}},
              ["employee"]),
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
    Tool("add_constraint", "Add a Constraint as provisional (not used until the leader confirms it on a propose_rule "
         "card). Prefer propose_rule.",
         _obj({"constraint": {"type": "object"}}, ["constraint"]), add_constraint, "mutation"),
    Tool("set_constraint_status", "Withdraw (rejected) or reopen (provisional) a rule you proposed. Confirming is the "
         "leader's call and only happens on a propose_rule card.",
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
    Tool("ask_confirm_tags", "Show the confirm_tags card: every role with automatic hazard/equipment tags, Keep or "
         "Remove each in one click. Only the owner's submission confirms or removes tags; you cannot.",
         _obj({}), ask_confirm_tags, "card"),
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
