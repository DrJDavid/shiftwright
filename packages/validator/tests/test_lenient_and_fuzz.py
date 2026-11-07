"""parse_schedule_lenient + fuzz: garbage in, violations out, never an exception."""
from __future__ import annotations

import copy
import json
import random

from shiftwright_contracts.models import ViolationCode
from shiftwright_validator import parse_schedule_lenient, validate

V = ViolationCode


def test_parse_valid_dict_round_trips(perfect):
    sched, problems = parse_schedule_lenient(perfect.model_dump(mode="json"))
    assert problems == []
    assert sched == perfect


def test_parse_json_string_inside_code_fence(perfect):
    text = "Here is the schedule:\n```json\n" + perfect.model_dump_json() + "\n```\nThanks!"
    sched, problems = parse_schedule_lenient(text)
    assert problems == []
    assert sched is not None and len(sched.shifts) == 6


def test_parse_not_json():
    sched, problems = parse_schedule_lenient("I cannot do that.")
    assert sched is None
    assert [p.code for p in problems] == [V.malformed]


def test_parse_wrong_top_level_type():
    for raw in (None, 42, [1, 2], "[]"):
        sched, problems = parse_schedule_lenient(raw)
        assert sched is None and problems and problems[0].code == V.malformed


def test_parse_drops_bad_shift_and_reports_it(perfect):
    raw = perfect.model_dump(mode="json")
    raw["shifts"][0]["day"] = 9
    del raw["shifts"][1]["employee_id"]
    sched, problems = parse_schedule_lenient(raw)
    assert sched is not None
    assert len(sched.shifts) == 4
    assert [p.code for p in problems] == [V.malformed, V.malformed]


def test_parse_hhmm_times_are_accepted(perfect):
    raw = perfect.model_dump(mode="json")
    raw["shifts"][0].update(start="09:00", end="13:00")
    raw["shifts"][0]["segments"][0].update(start="9:00", end="13:00")
    sched, problems = parse_schedule_lenient(raw)
    assert problems == []
    assert sched.shifts[0].start == 540 and sched.shifts[0].end == 780


def test_parse_missing_header_fields_still_gives_schedule():
    raw = {"shifts": [{"id": "x", "employee_id": "e2", "day": 0, "start": 540, "end": 780,
                       "segments": [{"role_id": "cashier", "start": 540, "end": 780}]}]}
    sched, problems = parse_schedule_lenient(raw)
    assert sched is not None and len(sched.shifts) == 1
    assert all(p.code == V.malformed for p in problems)


def test_end_before_start_is_malformed_not_a_crash(config, perfect):
    perfect.shifts[2].end = 500
    report = validate(config, perfect)
    assert V.malformed in {v.code for v in report.violations}


# --------------------------------------------------------------------------- #
# Fuzz
# --------------------------------------------------------------------------- #
WEIRD_VALUES = [None, -1, 0, 1, 7, 9999999, -9999999, 1e308, float("nan"), "", "abc", "25:99",
                "13:00", [], {}, True, 3.7, "e1", "ghost", "cashier", "astronaut"]


def all_paths(node, prefix=()):
    """Every (path) into a nested dict/list structure."""
    yield prefix
    if isinstance(node, dict):
        for k, v in node.items():
            yield from all_paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from all_paths(v, prefix + (i,))


def get_parent(root, path):
    node = root
    for p in path[:-1]:
        node = node[p]
    return node


def mutate(raw: dict, rng: random.Random) -> dict:
    raw = copy.deepcopy(raw)
    for _ in range(rng.randint(1, 4)):
        paths = [p for p in all_paths(raw) if p]
        if not paths:
            break
        path = rng.choice(paths)
        parent = get_parent(raw, path)
        key = path[-1]
        op = rng.choice(["set", "delete", "dup", "shift_time", "swap_id"])
        try:
            if op == "set":
                parent[key] = rng.choice(WEIRD_VALUES)
            elif op == "delete":
                del parent[key]
            elif op == "dup" and isinstance(parent, list):
                parent.append(copy.deepcopy(parent[key]))
            elif op == "shift_time" and isinstance(parent[key], int) and not isinstance(parent[key], bool):
                parent[key] = parent[key] + rng.choice([-1440, -61, -30, -1, 1, 15, 30, 600, 1440])
            elif op == "swap_id":
                parent[key] = rng.choice(["e1", "e2", "e3", "e4", "e5", "e6", "ghost",
                                          "cashier", "leader", "pit_operator", "stocker"])
        except (KeyError, IndexError, TypeError):
            pass
    return raw


def test_fuzz_200_mutations_never_raise(config, perfect):
    rng = random.Random(20261107)
    base = perfect.model_dump(mode="json")
    seen_codes: set = set()
    for i in range(200):
        raw = mutate(base, rng)
        as_text = rng.random() < 0.2
        payload = json.dumps(raw, allow_nan=True) if as_text else raw
        sched, problems = parse_schedule_lenient(payload)
        for p in problems:
            seen_codes.add(p.code)
        if sched is not None:
            report = validate(config, sched)
            assert report.hard_count == sum(1 for v in report.violations if v.severity == "hard")
            for v in report.violations:
                seen_codes.add(v.code)
                assert "could not evaluate" not in v.message, v.message  # no check crashed
    # sanity: the fuzzer actually produced trouble
    assert V.malformed in seen_codes


def test_fuzz_validate_on_constructed_garbage(config, perfect):
    """model_construct skips pydantic validation, like a careless caller might."""
    from shiftwright_contracts.models import Schedule, Shift

    rng = random.Random(7)
    for _ in range(50):
        bad = Shift.model_construct(
            id="x", employee_id=rng.choice(["e1", "ghost", None]), day=rng.choice([0, 1, 6, 12, -3]),
            start=rng.choice([0, 540, 1500, -60]), end=rng.choice([0, 780, 3000, 10**9]),
            breaks=rng.choice([[], None]), segments=rng.choice([[], None, perfect.shifts[0].segments]),
        )
        sched = Schedule.model_construct(**{**perfect.__dict__, "shifts": [bad, *perfect.shifts]})
        report = validate(config, sched)
        assert report.passed is False
        assert not any("could not evaluate" in v.message for v in report.violations), \
            [v.message for v in report.violations]
