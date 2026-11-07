"""Acceptance tests for fixtures/tiny_store.json (WS4 deliverable 1)."""
from pathlib import Path

import pytest
from shiftwright_contracts.models import StoreConfig

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tiny_store.json"


@pytest.fixture(scope="module")
def cfg() -> StoreConfig:
    return StoreConfig.model_validate_json(FIXTURE.read_text())


def test_validates_against_storeconfig(cfg):
    assert cfg.store.jurisdiction.state == "TX"


def test_shape(cfg):
    assert len(cfg.employees) == 6
    assert len(cfg.roles) == 4
    assert len(cfg.store.hours) == 2  # two open days, rest of week closed
    assert cfg.store.slot_minutes == 30
    assert cfg.store.week_start.weekday() == 0  # Monday


def test_ids_unique_and_references_resolve(cfg):
    dept_ids = {d.id for d in cfg.departments}
    role_ids = {r.id for r in cfg.roles}
    emp_ids = {e.id for e in cfg.employees}
    assert len(role_ids) == len(cfg.roles)
    assert len(emp_ids) == len(cfg.employees)
    assert all(r.department_id in dept_ids for r in cfg.roles)
    for e in cfg.employees:
        assert e.home_department_id in dept_ids
        assert set(e.trained_role_ids) <= role_ids
    event_ids = {ev.id for ev in cfg.events}
    for d in cfg.demand:
        assert d.role_id in role_ids
        assert d.event_id is None or d.event_id in event_ids
    assert set(cfg.role_tags) <= role_ids
    for c in cfg.constraints:
        if c.applies_to_employee_ids:
            assert set(c.applies_to_employee_ids) <= emp_ids
        for eid in c.params.get("employee_ids", []):
            assert eid in emp_ids


def test_times_on_slot_grid(cfg):
    slot = cfg.store.slot_minutes
    times = [t for h in cfg.store.hours for t in (h.open, h.close)]
    times += [t for d in cfg.demand for t in (d.start, d.end)]
    times += [t for ev in cfg.events for t in (ev.start, ev.end)]
    times += [t for e in cfg.employees for a in e.availability for t in (a.start, a.end)]
    assert all(t % slot == 0 for t in times)


def test_demand_on_open_days_within_staff_window(cfg):
    hours = {h.day: h for h in cfg.store.hours}
    for d in cfg.demand:
        assert d.day in hours
        h = hours[d.day]
        assert d.start >= h.open - cfg.store.pre_open_minutes
        assert d.end <= h.close + cfg.store.post_close_minutes
        assert d.start < d.end


def test_demand_intervals_for_same_role_do_not_overlap(cfg):
    """Requirements are not additive: one headcount per (role, day, slot)."""
    by_key: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for d in cfg.demand:
        by_key.setdefault((d.role_id, d.day), []).append((d.start, d.end))
    for spans in by_key.values():
        spans.sort()
        for (_, e1), (s2, _) in zip(spans, spans[1:]):
            assert e1 <= s2


def test_every_demanded_role_has_trained_employee(cfg):
    trained = {r for e in cfg.employees for r in e.trained_role_ids}
    assert {d.role_id for d in cfg.demand} <= trained


def test_hand_checkable_features(cfg):
    """The cases other workstreams rely on for hand checks."""
    roles = {r.id: r for r in cfg.roles}
    assert roles["pit_operator"].min_age == 18
    assert cfg.role_tags["pit_operator"] == ["powered_industrial_truck"]
    minors_on_pit = [e for e in cfg.employees if e.age < 18 and "pit_operator" in e.trained_role_ids]
    assert len(minors_on_pit) == 1  # the law trap: trained, but must never be scheduled on PIT
    kinds = {c.kind.value for c in cfg.constraints}
    assert {"always_staffed", "not_together"} <= kinds
    assert any(ev.kind.value == "truck" for ev in cfg.events)


def test_soft_constraints_have_weights(cfg):
    for c in cfg.constraints:
        if c.strength.value == "soft":
            assert c.weight_dollars > 0
        assert c.source.value != "law"  # law comes from data/laws, never baked into fixtures


def test_full_coverage_fits_budget(cfg):
    need = sum(d.headcount * (d.end - d.start) / 60 for d in cfg.demand)
    assert need <= cfg.budget.weekly_hours_cap
