"""Audit the engine as a black box: solve scenarios, validate every schedule, list disagreements.

A disagreement is any hard violation or any metrics_mismatch in a schedule the engine returned,
except two things that are expected by contract and listed as `expected` instead:
  * `below_minimum_wage` (SEMANTICS #15: the engine never changes wages; readiness flags them);
  * the hard violations of an empty schedule the engine marked `infeasible` (there is nothing to
    check; whether infeasible was the right answer is noted separately).
Dev-only: imports shiftwright_engine / shiftwright_scenarios / shiftwright_laws lazily, so the
validator itself keeps depending on the contracts alone. Never reads engine source; only calls
`solve_week` and `fix_day`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from shiftwright_contracts.models import Schedule, StoreConfig, ViolationCode

from .validate import validate

S_DIFFICULTIES = [("easy", "TX"), ("normal", "TX"), ("tight", "TX"), ("legal_trap", "TX"),
                  ("legal_trap", "CA"), ("infeasible", "TX"), ("messy", "TX")]


@dataclass
class Case:
    name: str
    config: StoreConfig
    expect_infeasible: bool = False


@dataclass
class AuditResult:
    name: str
    status: str
    seconds: float
    shifts: int
    hard_count: int
    disagreements: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)
    note: str = ""

    def line(self) -> str:
        return (f"{self.name:28s} {self.status:10s} {self.seconds:5.1f}s shifts={self.shifts:3d} "
                f"hard={self.hard_count} disagreements={len(self.disagreements)} "
                f"expected={len(self.expected)} {self.note}")

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def with_law_pack(config: StoreConfig) -> StoreConfig:
    """Attach the real law pack for the store's jurisdiction, as the API and evals do."""
    from shiftwright_laws import resolve

    config = config.model_copy(deep=True)
    if config.law_pack is None:
        config.law_pack = resolve(config.store.jurisdiction)
    return config


def default_cases(seeds=(1, 2, 3), difficulties=S_DIFFICULTIES, fixtures=True) -> list[Case]:
    from shiftwright_scenarios import generate, load_demo_store, load_tiny_store

    cases = []
    for difficulty, state in difficulties:
        for seed in seeds:
            sc = generate(seed, "S", difficulty, state)
            cases.append(Case(f"S/{difficulty}/{state}/{seed}", with_law_pack(sc.config),
                              bool(sc.expected.get("infeasible"))))
    if fixtures:
        cases.append(Case("tiny_store", with_law_pack(load_tiny_store())))
        cases.append(Case("demo_store", with_law_pack(load_demo_store())))
    return cases


EXPECTED_CODES = {ViolationCode.below_minimum_wage}


def classify(config: StoreConfig, schedule: Schedule, label: str = "") -> tuple[int, list[str], list[str]]:
    """(hard_count, disagreements, expected findings) for one engine schedule."""
    report = validate(config, schedule)
    empty_infeasible = schedule.status == "infeasible" and not schedule.shifts
    found, expected = [], []
    for v in report.violations:
        if v.severity != "hard" and v.code != ViolationCode.metrics_mismatch:
            continue
        where = " ".join(f"{k}={getattr(v, k)}" for k in
                         ("employee_id", "role_id", "day", "start", "end", "constraint_id", "law_rule_id")
                         if getattr(v, k) is not None)
        text = f"{label}{v.code.value}: {v.message} [{where}]"
        if v.code in EXPECTED_CODES or (empty_infeasible and v.code != ViolationCode.metrics_mismatch):
            expected.append(text)
        else:
            found.append(text)
    return report.hard_count, found, expected


def disagreements(config: StoreConfig, schedule: Schedule, label: str = "") -> list[str]:
    return classify(config, schedule, label)[1]


def audit_cases(cases, time_limit_s: float = 30):
    from shiftwright_engine import solve_week

    for case in cases:
        t0 = time.time()
        try:
            schedule = solve_week(case.config, time_limit_s=time_limit_s)
        except Exception as exc:  # noqa: BLE001 - an engine crash is itself a finding
            yield AuditResult(case.name, "CRASH", time.time() - t0, 0, 0,
                              [f"engine raised {type(exc).__name__}: {exc}"])
            continue
        seconds = time.time() - t0
        hard_count, found, expected = classify(case.config, schedule)
        note = ""
        if schedule.status not in ("optimal", "feasible", "infeasible"):
            found.append(f"engine returned status {schedule.status!r}: "
                         f"{(schedule.solver_stats or {}).get('error', '')}")
        if case.expect_infeasible and schedule.status != "infeasible":
            note = "(scenario expected infeasible)"
        if not case.expect_infeasible and schedule.status == "infeasible":
            summary = schedule.infeasibility.summary if schedule.infeasibility else ""
            note = f"(scenario expected feasible; engine: {summary})"
        if seconds > time_limit_s * 1.1:
            note += f" (over the {time_limit_s:g}s limit)"
        yield AuditResult(case.name, schedule.status, seconds, len(schedule.shifts), hard_count,
                          found, expected, note.strip())


@dataclass
class FixAuditResult:
    name: str
    mode: str | None
    plan_mode: str
    seconds: float
    callouts: list[str]
    disagreements: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"{self.name:28s} fix mode={self.mode}->{self.plan_mode} {self.seconds:4.1f}s "
                f"callouts={','.join(self.callouts)} disagreements={len(self.disagreements)} "
                f"expected={len(self.expected)}")


def classify_fix(request, plan) -> tuple[list[str], list[str]]:
    """(disagreements, expected) for a FixPlan, using validate_fix."""
    from .fix import validate_fix

    found, expected = [], []
    for v in validate_fix(request, plan).violations:
        if v.severity != "hard" and v.code != ViolationCode.metrics_mismatch:
            continue
        text = f"{v.code.value}: {v.message}"
        (expected if v.code in EXPECTED_CODES else found).append(text)
    return found, expected


def audit_fix(case: Case, schedule: Schedule, day: int, n: int = 3, now: int | None = None,
              modes=(None,), callout_ids: list[str] | None = None, time_limit_s: float = 8):
    """Call fix_day on `schedule` for a few call-outs and validate each plan."""
    from shiftwright_contracts.models import CallOut, FixRequest
    from shiftwright_engine import fix_day
    from shiftwright_scenarios import pick_callouts

    if callout_ids is not None:
        callouts = [CallOut(employee_id=e, day=day, reported_at=now if now is not None else 364)
                    for e in callout_ids]
    else:
        kw = {} if now is None else {"now": now}
        callouts = pick_callouts(case.config, schedule, day, n=n, **kw)
    if not callouts:
        return
    for mode in modes:
        req = FixRequest(config=case.config, schedule=schedule, callouts=callouts, day=day,
                         now=callouts[0].reported_at, outreach_mode=mode)
        t0 = time.time()
        try:
            plan = fix_day(req, time_limit_s=time_limit_s)
        except Exception as exc:  # noqa: BLE001
            yield FixAuditResult(case.name, mode, "CRASH", time.time() - t0,
                                 [c.employee_id for c in callouts],
                                 [f"fix_day raised {type(exc).__name__}: {exc}"])
            continue
        found, expected = classify_fix(req, plan)
        yield FixAuditResult(case.name, mode, plan.outreach_mode, time.time() - t0,
                             [c.employee_id for c in callouts], found, expected)
