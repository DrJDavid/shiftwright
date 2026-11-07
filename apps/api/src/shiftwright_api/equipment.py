"""Hazard / equipment role tagging (classification by role name, not law).

Roles created from a CSV import or in chat whose name or id matches keywords for a `ROLE_TAGS` tag
(forklift -> powered_industrial_truck, fry cook -> fryer + cooking, deli slicer -> meat_slicer,
bartender -> alcohol_service, ...) get that tag right away, so the law pack's `minor_prohibited_roles`
rules apply, and are recorded as "auto" until the leader confirms or rejects them. Which tags a law
bans, and at what ages, comes only from data/laws.

Review state lives in kv `equipment_review` {role_id: {"status": auto|confirmed|rejected, "tags": [...]}}
(the v1.3 form {role_id: "auto"} is read as powered_industrial_truck).
"""
from __future__ import annotations

import re

from shiftwright_contracts.models import ROLE_TAGS

from .db import Database

PIT_TAG = "powered_industrial_truck"

_PATTERNS: dict[str, list[str]] = {
    "powered_industrial_truck": [
        r"fork ?lifts?", r"pit", r"p i t", r"powered industrial", r"industrial truck", r"lift trucks?",
        r"reach (truck|lift)s?", r"(electric|powered|motori[sz]ed|ride on|rider) pallet (jack|truck)s?",
        r"pallet (jack|truck) (electric|powered|rider)", r"rider jacks?", r"walkie (rider|stacker)s?",
        r"(electric|powered) stackers?", r"order picker (lift|truck)s?", r"cherry pickers?", r"turret trucks?",
        r"hi ?lo", r"high ?lo", r"tow tractor", r"sit down rider", r"stand up rider", r"clamp trucks?",
        r"swing reach"],
    "meat_slicer": [r"slicers?", r"deli", r"butcher", r"meat (cutter|room|processing|department|dept)",
                    r"charcuterie"],
    "bakery_machine": [r"bakery", r"bakers?", r"dough", r"mixer operator", r"bread"],
    "baler_compactor": [r"balers?", r"compactors?", r"box crusher", r"cardboard"],
    "motor_vehicle_driving": [r"drivers?", r"delivery driver", r"courier", r"valet", r"shuttle", r"chauffeur",
                              r"van", r"delivery"],
    "cooking": [r"cooks?", r"line cook", r"chef", r"sous", r"grill", r"griddle", r"broiler", r"saute",
                r"fry cook", r"kitchen lead", r"pizzaiolo", r"taquero", r"tortillas?"],
    "fryer": [r"fry", r"fryers?", r"fries", r"fry cook"],
    "power_saw": [r"saws?", r"lumber", r"cut (desk|center|shop)", r"millwork", r"key cutting"],
    "ladder_scaffold": [r"ladders?", r"scaffold(ing)?", r"high bay", r"rigger"],
    "alcohol_service": [r"bartenders?", r"bar", r"barback", r"sommelier", r"liquor", r"wine", r"beer",
                        r"cocktail", r"mixologist", r"beverage service"],
}
_NOT = {  # names that contain a keyword but are a different job
    "motor_vehicle_driving": re.compile(r"\bdrive (up|thru|through)\b|\bdelivery (receiv|clerk|dock)"),
    "cooking": re.compile(r"\bdish|\bprep\b(?! cook)"),
    "alcohol_service": re.compile(r"\bbar ?code|\bbarista"),
}
_RX = {tag: re.compile(r"\b(" + "|".join(p) + r")\b") for tag, p in _PATTERNS.items()}
assert set(_RX) <= set(ROLE_TAGS)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def tags_for(role_id: str, name: str) -> list[str]:
    texts = [_norm(name), _norm(role_id)]
    out = []
    for tag, rx in _RX.items():
        if any(rx.search(t) and not (tag in _NOT and _NOT[tag].search(t)) for t in texts):
            out.append(tag)
    return out


def looks_powered(role_id: str, name: str) -> bool:
    return PIT_TAG in tags_for(role_id, name)


def state(db: Database, store_id: str) -> dict[str, dict]:
    raw = db.get(store_id, "equipment_review", "roles") or {}
    return {rid: (v if isinstance(v, dict) else {"status": v, "tags": [PIT_TAG]}) for rid, v in raw.items()}


def tag_in_dict(d: dict, review: dict[str, dict]) -> list[tuple[str, str, list[str]]]:
    """Inside a config mutation: tag newly seen hazard roles. Returns [(role_id, name, tags_added)]."""
    out = []
    for r in d["roles"]:
        if r["id"] in review:
            continue
        have = d["role_tags"].get(r["id"], [])
        new = [t for t in tags_for(r["id"], r.get("name", "")) if t not in have]
        if not new:
            continue
        d["role_tags"][r["id"]] = have + new
        out.append((r["id"], r.get("name", r["id"]), new))
    return out


def record_auto(db: Database, store_id: str, tagged: list) -> None:
    if tagged:
        review = state(db, store_id)
        for rid, _, tags in tagged:
            review[rid] = {"status": "auto", "tags": list(tags)}
        db.put(store_id, "equipment_review", "roles", review)


def describe(tagged: list) -> str:
    return ", ".join(f"{name} ({', '.join(tags)})" for _, name, tags in tagged)


def decide(db: Database, store_id: str, role_id: str, decision: str):
    """Leader confirms (keep) or rejects (remove) the automatic tags on a role. Returns the new config."""
    if decision not in ("confirm", "reject"):
        raise ValueError("decision must be 'confirm' or 'reject'")
    cfg = db.get_config(store_id)
    if role_id not in {r.id for r in cfg.roles}:
        raise KeyError(role_id)
    review = state(db, store_id)
    entry = review.get(role_id) or {"status": "auto", "tags": list(cfg.role_tags.get(role_id, [])) or [PIT_TAG]}
    auto_tags = entry.get("tags") or [PIT_TAG]

    def fn(d):
        tags = [t for t in d["role_tags"].get(role_id, []) if t not in auto_tags]
        if decision == "confirm":
            tags += auto_tags
        if tags:
            d["role_tags"][role_id] = tags
        else:
            d["role_tags"].pop(role_id, None)
    new = db.mutate(store_id, fn, f"equipment:{decision}", {"role_id": role_id, "tags": auto_tags}, "leader")
    review[role_id] = {"status": "confirmed" if decision == "confirm" else "rejected", "tags": auto_tags}
    db.put(store_id, "equipment_review", "roles", review)
    return new


def pending(db: Database, store_id: str) -> list[str]:
    return [rid for rid, v in state(db, store_id).items() if v.get("status") == "auto"]
