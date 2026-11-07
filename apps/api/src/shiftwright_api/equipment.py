"""Powered-equipment role detection (classification by name, not law).

Roles created from a CSV import or in chat that look like powered industrial trucks (forklift, PIT,
reach truck, electric pallet jack, ...) are tagged `powered_industrial_truck` right away, so the law
pack's `minor_prohibited_roles` rule applies to them, and recorded as "auto" until the leader confirms
or rejects the tag. Review state lives in kv `equipment_review` {role_id: "auto"|"confirmed"|"rejected"}.
"""
from __future__ import annotations

import re

from .db import Database

PIT_TAG = "powered_industrial_truck"

_PATTERNS = [
    r"fork ?lifts?", r"pit", r"p i t", r"powered industrial", r"industrial truck", r"lift trucks?",
    r"reach (truck|lift)s?", r"(electric|powered|motori[sz]ed|ride on|rider) pallet (jack|truck)s?",
    r"pallet (jack|truck) (electric|powered|rider)", r"rider jacks?", r"walkie (rider|stacker)s?", r"(electric|powered) stackers?",
    r"order picker (lift|truck)s?", r"cherry pickers?", r"turret trucks?", r"hi ?lo", r"high ?lo", r"tow tractor",
    r"(scissor|boom|aerial|man) lifts?", r"sit down rider", r"stand up rider", r"clamp trucks?", r"swing reach",
]
_RX = re.compile(r"\b(" + "|".join(_PATTERNS) + r")\b")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def looks_powered(role_id: str, name: str) -> bool:
    return bool(_RX.search(_norm(name)) or _RX.search(_norm(role_id)))


def state(db: Database, store_id: str) -> dict[str, str]:
    return db.get(store_id, "equipment_review", "roles") or {}


def tag_in_dict(d: dict, review: dict[str, str]) -> list[tuple[str, str]]:
    """Inside a config mutation: tag newly seen powered-equipment roles. Returns [(role_id, name)] tagged."""
    out = []
    for r in d["roles"]:
        tags = d["role_tags"].get(r["id"], [])
        if r["id"] in review or PIT_TAG in tags or not looks_powered(r["id"], r.get("name", "")):
            continue
        d["role_tags"][r["id"]] = tags + [PIT_TAG]
        out.append((r["id"], r.get("name", r["id"])))
    return out


def record_auto(db: Database, store_id: str, tagged: list[tuple[str, str]]) -> None:
    if tagged:
        review = state(db, store_id)
        review.update({rid: "auto" for rid, _ in tagged})
        db.put(store_id, "equipment_review", "roles", review)


def decide(db: Database, store_id: str, role_id: str, decision: str):
    """Leader confirms (keep tag) or rejects (remove tag) an equipment role. Returns the new config."""
    if decision not in ("confirm", "reject"):
        raise ValueError("decision must be 'confirm' or 'reject'")
    cfg = db.get_config(store_id)
    if role_id not in {r.id for r in cfg.roles}:
        raise KeyError(role_id)

    def fn(d):
        tags = [t for t in d["role_tags"].get(role_id, []) if t != PIT_TAG]
        if decision == "confirm":
            tags.append(PIT_TAG)
        if tags:
            d["role_tags"][role_id] = tags
        else:
            d["role_tags"].pop(role_id, None)
    new = db.mutate(store_id, fn, f"equipment:{decision}", {"role_id": role_id}, "leader")
    review = state(db, store_id)
    review[role_id] = "confirmed" if decision == "confirm" else "rejected"
    db.put(store_id, "equipment_review", "roles", review)
    return new


def pending(db: Database, store_id: str) -> list[str]:
    return [rid for rid, s in state(db, store_id).items() if s == "auto"]
