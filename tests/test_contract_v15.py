"""Contract v1.5 checks that span workstreams: role tags come from ROLE_TAGS everywhere."""
import json
from pathlib import Path

from shiftwright_contracts.models import ROLE_TAGS, StoreConfig

ROOT = Path(__file__).resolve().parents[1]


def _law_role_tags():
    for path in (ROOT / "data" / "laws").rglob("*.json"):
        data = json.loads(path.read_text())
        rules = data.get("rules", []) if isinstance(data, dict) else []
        for rule in rules:
            for tag in (rule.get("params") or {}).get("role_tags", []) or []:
                yield path.name, tag


def test_law_data_uses_known_role_tags():
    unknown = sorted({(f, t) for f, t in _law_role_tags() if t not in ROLE_TAGS})
    assert not unknown, unknown


def test_fixture_role_tags_are_known_and_fixtures_load():
    fixtures = list((ROOT / "packages" / "scenarios" / "fixtures").glob("*store*.json"))
    assert fixtures
    for path in fixtures:
        cfg = StoreConfig.model_validate_json(path.read_text())
        for role_id, tags in cfg.role_tags.items():
            assert set(tags) <= set(ROLE_TAGS), (path.name, role_id, tags)
