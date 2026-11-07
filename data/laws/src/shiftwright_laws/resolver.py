"""Resolve federal + state + city law files into one LawPack.

Merge policy (brief: "keep the more protective one for the worker"):

* Pay-rate rules (weekly/daily overtime, minimum wage) are *exclusive*: the engine
  must price an hour once, so only the single most protective rule is kept.
* Every other rule type is a *limit* (breaks, minor hours, prohibited roles, rest
  between shifts, predictive scheduling, reporting-time pay). When several
  jurisdictions set limits, the worker is owed all of them, so all are kept, each
  with its own citation; enforcing every one is the same as enforcing the strictest.
"""
from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from shiftwright_contracts.models import Jurisdiction, LawPack, LawRule, LawRuleType as T

LAWS_DIR = Path(os.environ.get("SHIFTWRIGHT_LAWS_DIR", Path(__file__).resolve().parents[2]))


def city_slug(city: str) -> str:
    return "-".join(city.strip().lower().replace(".", "").split())


def _path(state: Optional[str] = None, city: Optional[str] = None) -> Path:
    if state is None:
        return LAWS_DIR / "federal.json"
    if city is None:
        return LAWS_DIR / "states" / f"{state.upper()}.json"
    return LAWS_DIR / "cities" / f"{state.lower()}-{city_slug(city)}.json"


@lru_cache(maxsize=None)
def _load(path: Path) -> Optional[tuple[LawRule, ...]]:
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    return tuple(LawRule(**r) for r in doc["rules"])


def load_notes(state: Optional[str] = None, city: Optional[str] = None) -> list[str]:
    """The `notes` of one file (e.g. 'no state meal-break law'), for answering law questions."""
    path = _path(state, city)
    return json.loads(path.read_text()).get("notes", []) if path.exists() else []


# Higher key = more protective for the worker.
def _ot_key(r: LawRule):
    return (-float(r.params["threshold_hours"]), float(r.params["multiplier"]))


def _wage_key(r: LawRule):
    return float(r.params["dollars_per_hour"])


def _tipped_key(r: LawRule):
    return float(r.params["cash_wage_per_hour"])


EXCLUSIVE: dict[T, Callable[[LawRule], object]] = {
    T.weekly_overtime: _ot_key,
    T.daily_overtime: _ot_key,
    T.minimum_wage: _wage_key,
}
LEVEL_RANK = {"federal": 0, "state": 1, "city": 2}


def _in_effect(r: LawRule, on: date) -> bool:
    eff = r.params.get("effective")
    return eff is None or date.fromisoformat(str(eff)) <= on


def _merge(rules: list[LawRule], on: date) -> list[LawRule]:
    kept: list[LawRule] = []
    for rtype, key in EXCLUSIVE.items():
        candidates = [r for r in rules if r.type == rtype and _in_effect(r, on)]
        if candidates:
            # most protective; ties go to the more local jurisdiction
            kept.append(max(candidates, key=lambda r: (key(r), LEVEL_RANK[r.level])))
    kept += _tipped(rules, kept, on)
    kept += [r for r in rules if r.type not in EXCLUSIVE and r.type != T.tipped_minimum_wage]
    return kept


def _tipped(rules: list[LawRule], kept: list[LawRule], on: date) -> list[LawRule]:
    """SEMANTICS #20: one tipped_minimum_wage rule (highest cash wage; ties -> more local).

    A tip credit only counts if it comes from the jurisdiction whose minimum wage applies (or a more
    local one): e.g. the federal $2.13 cash wage never applies in a state with its own higher minimum
    wage and no state tip credit (CA, WA). No tipped rule => tipped employees get the full minimum wage."""
    wage = next((r for r in kept if r.type == T.minimum_wage), None)
    floor = LEVEL_RANK[wage.level] if wage else 0
    candidates = [r for r in rules if r.type == T.tipped_minimum_wage and _in_effect(r, on)
                  and LEVEL_RANK[r.level] >= floor]
    if not candidates:
        return []
    return [max(candidates, key=lambda r: (_tipped_key(r), LEVEL_RANK[r.level]))]


def resolve(
    jurisdiction: Jurisdiction | str,
    city: Optional[str] = None,
    *,
    include_low_confidence: bool = False,
    on: Optional[date] = None,
) -> LawPack:
    """`resolve(Jurisdiction(state="TX", city="austin"))` or `resolve("TX", "austin")`."""
    if isinstance(jurisdiction, str):
        jurisdiction = Jurisdiction(state=jurisdiction, city=city)
    state = jurisdiction.state.strip().upper()
    city_name = jurisdiction.city.strip().lower() if jurisdiction.city else None
    jur = Jurisdiction(state=state, city=city_name)
    on = on or date.today()

    rules = list(_load(_path()) or ())
    warnings: list[str] = []
    state_rules = _load(_path(state))
    if state_rules is None:
        coverage = "federal_fallback"
        warnings.append(f"No dataset entry for state '{state}'; only federal rules are applied.")
    else:
        rules += state_rules
        coverage = "full"
        if city_name:
            city_rules = _load(_path(state, city_name))
            if city_rules is None:
                coverage = "state_only"
                warnings.append(f"No dataset entry for city '{city_name}'; state + federal applied.")
            else:
                rules += city_rules

    if not include_low_confidence:
        rules = [r for r in rules if r.confidence != "low"]
    return LawPack(jurisdiction=jur, rules=_merge(rules, on), coverage=coverage, warnings=warnings)
