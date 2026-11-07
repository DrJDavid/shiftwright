"""Independent schedule rule checker (WS2).

Shares no code with the engine; built only from contracts/ and briefs/WS2-validator.md.

    validate(config, schedule) -> ValidationReport
    parse_schedule_lenient(raw) -> (Schedule | None, [Violation])
    recompute_metrics(config, schedule) -> ScheduleMetrics
    validate_raw(config, raw) -> ValidationReport   # parse + validate, for baseline outputs
"""
from .metrics import recompute_metrics
from .parse import parse_schedule_lenient
from .validate import validate, validate_raw

__all__ = ["validate", "validate_raw", "parse_schedule_lenient", "recompute_metrics"]
