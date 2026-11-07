"""Every data file validates against the contract and carries a citation."""
import json
from pathlib import Path

import pytest
from shiftwright_contracts.models import LawRule, LawRuleType

LAWS_DIR = Path(__file__).resolve().parents[1]
FILES = [LAWS_DIR / "federal.json", *sorted((LAWS_DIR / "states").glob("*.json")),
         *sorted(p for p in (LAWS_DIR / "cities").glob("*.json") if not p.name.startswith("_"))]

REQUIRED_PARAMS = {
    LawRuleType.weekly_overtime: {"threshold_hours", "multiplier"},
    LawRuleType.daily_overtime: {"threshold_hours", "multiplier", "double_threshold_hours"},
    LawRuleType.meal_break: {"after_minutes", "duration", "paid"},
    LawRuleType.rest_break: {"per_minutes_worked", "duration", "paid"},
    LawRuleType.minor_limits: {"age_min", "age_max", "school_week"},
    LawRuleType.minor_prohibited_roles: {"age_below", "role_tags"},
    LawRuleType.min_rest_between_shifts: {"minutes", "waivable"},
    LawRuleType.predictive_scheduling: {"notice_days", "change_premium_hours", "applies_to"},
    LawRuleType.reporting_time_pay: set(),
    LawRuleType.minimum_wage: {"dollars_per_hour", "effective"},
    LawRuleType.tipped_minimum_wage: {"cash_wage_per_hour", "max_tip_credit_per_hour", "effective"},
}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_file_validates(path: Path):
    doc = json.loads(path.read_text())
    assert {"jurisdiction", "level", "notes", "rules"} <= doc.keys()
    ids = set()
    for raw in doc["rules"]:
        rule = LawRule(**raw)
        assert rule.id not in ids, f"duplicate id {rule.id}"
        ids.add(rule.id)
        assert rule.level == doc["level"]
        assert rule.jurisdiction.state == doc["jurisdiction"]["state"]
        assert rule.citation.url.startswith("http")
        assert rule.citation.last_verified
        assert len(rule.citation.excerpt.split()) <= 40
        assert REQUIRED_PARAMS[rule.type] <= rule.params.keys(), rule.id


def test_city_index_lists_every_city_file():
    index = json.loads((LAWS_DIR / "cities" / "_index.json").read_text())
    listed = {c["file"] for c in index["cities"]}
    on_disk = {p.name for p in (LAWS_DIR / "cities").glob("*.json") if not p.name.startswith("_")}
    assert listed == on_disk
