"""Eval cases. Every case is a seeded scenario from shiftwright_scenarios with the law pack resolved."""
from __future__ import annotations

from dataclasses import dataclass, field

from shiftwright_contracts.models import StoreConfig
from shiftwright_laws import resolve
from shiftwright_scenarios import Scenario, generate

SUITES = ["weekly", "honesty", "repair", "realistic"]
REPAIR_NOW = 6 * 60 + 4  # 06:04, as in the demo script

# Scenarios whose `expected` flag is known to be wrong (decided by David, Sat Nov 7). A system that says
# "infeasible" on one of these is not scored as a false "infeasible"; the report lists them.
SUSPECT_EXPECTED: dict[str, str] = {
    # weekly-S-legal_trap-CA-s1 was listed here until WS4 set max_shifts_per_day=2 for CA legal_trap
    # (David, Sat Nov 7): it is feasible (a baseline found a clean schedule), so "infeasible" there is an FP.
}


@dataclass
class Case:
    suite: str
    scenario_id: str
    size: str
    difficulty: str
    seed: int
    jurisdiction: str
    scenario: Scenario = field(repr=False)

    @property
    def config(self) -> StoreConfig:
        return self.scenario.config

    @property
    def expected_suspect(self) -> str | None:
        return SUSPECT_EXPECTED.get(self.scenario_id)

    @property
    def expected_infeasible(self) -> bool:
        return bool(self.scenario.expected.get("infeasible"))


def make_case(suite: str, size: str, difficulty: str, seed: int, jurisdiction: str = "TX",
              sector: str = "retail") -> Case:
    sc = generate(seed, size, difficulty, jurisdiction, **({"sector": sector} if sector != "retail" else {}))
    sc.config.law_pack = resolve(sc.config.store.jurisdiction)
    jur = jurisdiction.replace("/", "-")
    sid = f"{suite}-{'food-' if sector == 'food' else ''}{size}-{difficulty}-{jur}-s{seed}"
    return Case(suite, sid, size, difficulty, seed, jurisdiction, sc)


def build_cases(suites: list[str], quick: bool) -> list[Case]:
    sizes = ["S", "M"] if quick else ["S", "M", "L"]
    seeds = [1] if quick else [1, 2, 3]
    cases: list[Case] = []
    if "weekly" in suites:
        for size in sizes:
            for diff in ["easy", "tight", "legal_trap"]:
                for seed in seeds:
                    # legal_trap uses CA so the meal/rest-break traps are live (WS4 STATUS).
                    cases.append(make_case("weekly", size, diff, seed, "CA" if diff == "legal_trap" else "TX"))
    if "honesty" in suites:
        h_seeds = [1] if quick else [1, 2]
        for size in sizes:
            for seed in h_seeds:
                cases.append(make_case("honesty", size, "infeasible", seed))
    if "realistic" in suites:
        from .realistic import realistic_cases
        cases.extend(realistic_cases(quick))
    if "repair" in suites:
        for size in ["S", "M"]:
            for seed in seeds:
                cases.append(make_case("repair", size, "normal", seed))
    return cases
