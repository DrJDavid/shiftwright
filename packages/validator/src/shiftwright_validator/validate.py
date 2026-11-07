"""validate(): run every check, never crash."""
from __future__ import annotations

from shiftwright_contracts.models import (
    Schedule,
    ScheduleMetrics,
    StoreConfig,
    ValidationReport,
    Violation,
    ViolationCode,
)

from .checks import ALL_CHECKS
from .context import build_context
from .metrics import Computed, compute
from .parse import parse_schedule_lenient


def _empty_metrics(config: StoreConfig) -> ScheduleMetrics:
    cap = config.budget.weekly_hours_cap + sum(a.extra_hours for a in config.budget.approvals)
    return ScheduleMetrics(total_hours=0, total_wage_cost=0, overtime_hours=0, coverage_pct=0,
                           gap_penalty_dollars=0, soft_penalty_dollars=0, objective_dollars=0,
                           budget_hours_cap=cap, budget_hours_used=0)


def _crash(where: str, exc: Exception) -> Violation:
    # A schema-valid but bizarre schedule tripped a check. Report it rather than crash the eval;
    # it counts as a hard failure so it can never make a bad schedule look good.
    return Violation(code=ViolationCode.malformed, severity="hard",
                     message=f"Validator could not evaluate {where}: {type(exc).__name__}: {exc}")


def validate(config: StoreConfig, schedule: Schedule) -> ValidationReport:
    violations: list[Violation] = []
    ctx = build_context(config, schedule)
    try:
        computed = compute(ctx)
    except Exception as exc:  # noqa: BLE001 - must never crash on garbage
        violations.append(_crash("metrics", exc))
        computed = Computed(metrics=_empty_metrics(config))

    for check in ALL_CHECKS:
        try:
            violations.extend(check(ctx, computed))
        except Exception as exc:  # noqa: BLE001
            violations.append(_crash(check.__name__, exc))

    hard_count = sum(1 for v in violations if v.severity == "hard")
    return ValidationReport(passed=hard_count == 0, hard_count=hard_count,
                            violations=violations, recomputed_metrics=computed.metrics)


def validate_raw(config: StoreConfig, raw) -> ValidationReport:
    """Parse anything (dict, JSON text, LLM reply) leniently, then validate it.
    Parse problems are included as violations. Unparseable input => one report with passed=False."""
    schedule, problems = parse_schedule_lenient(raw)
    if schedule is None:
        return ValidationReport(passed=False, hard_count=len(problems), violations=problems,
                                recomputed_metrics=_empty_metrics(config))
    report = validate(config, schedule)
    violations = problems + report.violations
    hard_count = sum(1 for v in violations if v.severity == "hard")
    return ValidationReport(passed=hard_count == 0, hard_count=hard_count, violations=violations,
                            recomputed_metrics=report.recomputed_metrics)
