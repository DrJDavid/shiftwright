"""parse_schedule_lenient(): turn whatever a model returned into a Schedule, reporting what was wrong.

Rules:
  * dict, Schedule, or text (JSON, JSON inside a ``` fence, or JSON embedded in prose) are accepted.
  * A schedule that validates strictly is returned with no problems.
  * Otherwise each bad piece is dropped and reported as `malformed`: a bad break or segment is
    dropped from its shift; a shift that still doesn't validate is dropped entirely.
  * "HH:MM" strings are accepted for times (LLMs love them) and are not reported.
  * Returns (None, [malformed]) only when there is no JSON object at all.
"""
from __future__ import annotations

import json
import re
from datetime import date

from pydantic import ValidationError

from shiftwright_contracts.models import (
    Break,
    Gap,
    Infeasibility,
    RoleSegment,
    Schedule,
    ScheduleMetrics,
    Shift,
    SoftViolation,
    Violation,
    ViolationCode,
)

FALLBACK_WEEK_START = date(1970, 1, 5)  # a Monday; will also fail the week_start check
STATUSES = ("optimal", "feasible", "infeasible", "error")
HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def problem(message: str) -> Violation:
    return Violation(code=ViolationCode.malformed, severity="hard", message=message)


def short_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc or 'value'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def load_json(raw, problems: list[Violation]):
    if isinstance(raw, Schedule):
        return raw.model_dump()
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        text = raw.strip()
        candidates = [text]
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            candidates.append(fence.group(1).strip())
        first, last = text.find("{"), text.rfind("}")
        if 0 <= first < last:
            candidates.append(text[first:last + 1])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                break
            except (ValueError, RecursionError):
                continue
        else:
            problems.append(problem("Output is not valid JSON."))
            return None
        raw = data
    if not isinstance(raw, dict):
        problems.append(problem(f"Expected a JSON object for the schedule, got {type(raw).__name__}."))
        return None
    return raw


def hhmm_to_minutes(value):
    if isinstance(value, str):
        m = HHMM.match(value)
        if m and int(m.group(2)) < 60:
            return int(m.group(1)) * 60 + int(m.group(2))
    return value


def normalize_times(item):
    if isinstance(item, dict):
        item = dict(item)
        for key in ("start", "end"):
            if key in item:
                item[key] = hhmm_to_minutes(item[key])
    return item


def keep_valid(items, model, label: str, problems: list[Violation]) -> list:
    """Validate each item of a list; drop and report the bad ones."""
    if items is None:
        return []
    if not isinstance(items, list):
        problems.append(problem(f"{label} is not a list; ignored."))
        return []
    kept = []
    for i, item in enumerate(items):
        try:
            kept.append(model.model_validate(normalize_times(item)))
        except ValidationError as exc:
            problems.append(problem(f"{label}[{i}] dropped: {short_error(exc)}"))
    return kept


def parse_shift(i: int, raw, problems: list[Violation]):
    if not isinstance(raw, dict):
        problems.append(problem(f"shifts[{i}] dropped: not an object."))
        return None
    data = normalize_times(raw)
    if "id" not in data:
        data["id"] = f"shift_{i}"
        problems.append(problem(f"shifts[{i}] has no id; named it shift_{i}."))
    data["breaks"] = keep_valid(data.get("breaks", []), Break, f"shifts[{i}].breaks", problems)
    data["segments"] = keep_valid(data.get("segments"), RoleSegment, f"shifts[{i}].segments", problems)
    try:
        return Shift.model_validate(data)
    except ValidationError as exc:
        problems.append(problem(f"shifts[{i}] dropped: {short_error(exc)}"))
        return None


def parse_schedule_lenient(raw) -> tuple[Schedule | None, list[Violation]]:
    problems: list[Violation] = []
    try:
        data = load_json(raw, problems)
        if data is None:
            return None, problems
        try:
            return Schedule.model_validate(data), []
        except ValidationError:
            pass
        return lenient(data, problems), problems
    except Exception as exc:  # noqa: BLE001 - garbage in must never mean a crash
        problems.append(problem(f"Could not parse schedule: {type(exc).__name__}: {exc}"))
        return None, problems


def lenient(data: dict, problems: list[Violation]) -> Schedule:
    store_id = data.get("store_id")
    if not isinstance(store_id, str):
        problems.append(problem("store_id missing or not a string."))
        store_id = ""
    try:
        week_start = date.fromisoformat(str(data.get("week_start")))
    except ValueError:
        problems.append(problem(f"week_start {data.get('week_start')!r} is not a date."))
        week_start = FALLBACK_WEEK_START
    config_version = data.get("config_version")
    if not isinstance(config_version, int) or isinstance(config_version, bool):
        problems.append(problem("config_version missing or not an integer."))
        config_version = 0
    produced_by = data.get("produced_by")
    if not isinstance(produced_by, str):
        problems.append(problem("produced_by missing or not a string."))
        produced_by = "unknown"
    status = data.get("status")
    if status not in STATUSES:
        problems.append(problem(f"status {status!r} is not one of {', '.join(STATUSES)}."))
        status = "error"

    raw_shifts = data.get("shifts", [])
    if not isinstance(raw_shifts, list):
        problems.append(problem("shifts is not a list; no shifts read."))
        raw_shifts = []
    shifts = [s for i, raw in enumerate(raw_shifts) if (s := parse_shift(i, raw, problems)) is not None]

    metrics = None
    if data.get("metrics") is not None:
        try:
            metrics = ScheduleMetrics.model_validate(data["metrics"])
        except ValidationError as exc:
            problems.append(problem(f"metrics ignored: {short_error(exc)}"))
    infeasibility = None
    if data.get("infeasibility") is not None:
        try:
            infeasibility = Infeasibility.model_validate(data["infeasibility"])
        except ValidationError as exc:
            problems.append(problem(f"infeasibility ignored: {short_error(exc)}"))
    solver_stats = data.get("solver_stats")
    if not isinstance(solver_stats, dict):
        solver_stats = {}

    return Schedule(
        store_id=store_id, week_start=week_start, config_version=config_version,
        produced_by=produced_by, status=status, shifts=shifts,
        gaps=keep_valid(data.get("gaps", []), Gap, "gaps", problems),
        soft_violations=keep_valid(data.get("soft_violations", []), SoftViolation, "soft_violations", problems),
        metrics=metrics, infeasibility=infeasibility, solver_stats=solver_stats,
    )
