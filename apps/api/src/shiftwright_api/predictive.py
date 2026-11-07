"""How outreach must be worded and sent under predictive-scheduling (Fair Workweek) rules.

Only reads law-pack params (SEMANTICS #17, data/laws "Extra param keys"); never computes amounts.
  * Seattle-style (`exemption_requires_group_message`): the offer goes to >= `exemption_min_recipients`
    people at once as a "mass communication" with the statements in `exemption_message_must_state`;
    a one-to-one text is not exempt.
  * Chicago-style (`voluntary_additional_hours_exempt` + written consent, text counts): one-to-one is
    exempt; the text says accepting is voluntary.
  * Otherwise: no exemption known, premium owed (the engine prices it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shiftwright_contracts.models import LawPack, LawRuleType, StoreConfig

VOLUNTARY = "Accepting is voluntary and you may decline."
_STATEMENTS = [  # (keyword in the law-pack statement, sentence we send)
    ("mass communication", "This is a mass communication sent to several employees."),
    ("voluntary", "Accepting these hours is voluntary and you may decline."),
    ("compensation", "Accepting does not earn additional compensation for schedule changes."),
]


@dataclass
class Policy:
    mode: str = "one_to_one"  # one_to_one | group_offer (contract literals, FixPlan.outreach_mode)
    min_recipients: int = 1
    sentences: list[str] = field(default_factory=list)
    premium_status: str = "not_applicable"  # not_applicable | exempt | owed
    law_rule_ids: list[str] = field(default_factory=list)
    note: str = ""

    def premium(self) -> dict:
        return {"status": self.premium_status, "law_rule_ids": self.law_rule_ids, "note": self.note}


def _applies(params: dict, count: Optional[int]) -> bool:
    if count is None:
        return True  # SEMANTICS #17: unknown employer size => the rule applies
    over = params.get("applies_if_employees_over")
    if over is not None and count <= over:
        return False
    least = params.get("min_covered_employees")
    return least is None or count >= least


def render(statements: list[str]) -> Optional[list[str]]:
    """Law-pack statement descriptions -> sentences. None if one can't be worded (then we don't claim exemption)."""
    out: list[str] = []
    for st in statements:
        hit = next((s for k, s in _STATEMENTS if k in st.lower()), None)
        if hit is None:
            return None
        if hit not in out:
            out.append(hit)
    return out


def _rules(config: StoreConfig, pack: Optional[LawPack]):
    return [r for r in (pack.rules if pack else []) if r.type == LawRuleType.predictive_scheduling
            and _applies(r.params, config.store.employer_employee_count)]


def preferred_mode(config: StoreConfig, pack: Optional[LawPack]) -> str:
    """FixRequest.outreach_mode: group_offer when an applicable rule needs a group message for the exemption
    (and we can word its required statements), else one_to_one."""
    for r in _rules(config, pack):
        p = r.params
        if (p.get("exemption_requires_group_message") and p.get("voluntary_additional_hours_exempt")
                and render(p.get("exemption_message_must_state") or []) is not None):
            return "group_offer"
    return "one_to_one"


def policy(config: StoreConfig, pack: Optional[LawPack], mode: Optional[str] = None) -> Policy:
    """How to send outreach in `mode` (default: preferred_mode) and whether a premium is owed."""
    mode = mode or preferred_mode(config, pack)
    rules = _rules(config, pack)
    if not rules:
        return Policy(mode=mode, min_recipients=2 if mode == "group_offer" else 1)
    ids = [r.id for r in rules]
    group = next((r for r in rules if r.params.get("exemption_requires_group_message")), None)
    if group is not None:
        p = group.params
        sentences = render(p.get("exemption_message_must_state") or [])
        n = max(2, int(p.get("exemption_min_recipients") or 2))
        if mode == "group_offer" and p.get("voluntary_additional_hours_exempt") and sentences is not None:
            return Policy(mode=mode, min_recipients=n, sentences=sentences, premium_status="exempt", law_rule_ids=ids,
                          note=f"Group offer (mass communication) under {group.id}: exempt if accepted. "
                               + (p.get("exemption_note") or ""))
        why = ("one-to-one texts are not exempt" if mode == "one_to_one"
               else "the dataset's required statements can't be worded")
        return Policy(mode=mode, min_recipients=n if mode == "group_offer" else 1, premium_status="owed",
                      law_rule_ids=ids, note=f"{group.id}: {why}; the plan's cost includes the premium.")
    p = rules[0].params
    written_ok = not p.get("consent_must_be_written") or p.get("text_message_counts_as_written")
    n = 2 if mode == "group_offer" else 1
    if all(r.params.get("voluntary_additional_hours_exempt") for r in rules) and written_ok:
        return Policy(mode=mode, min_recipients=n, sentences=[VOLUNTARY], premium_status="exempt", law_rule_ids=ids,
                      note=f"Voluntary call-in accepted by text: exempt under {', '.join(ids)}. "
                           + (p.get("exemption_note") or ""))
    return Policy(mode=mode, min_recipients=n, premium_status="owed", law_rule_ids=ids,
                  note=f"No exemption for call-ins in {', '.join(ids)}; the plan's cost includes the premium.")
