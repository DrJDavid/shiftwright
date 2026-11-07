"""API-local helper shapes from contracts/API.md (not in contracts/models.py)."""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from shiftwright_contracts.models import InboundMessage, Jurisdiction, OutboundMessage, Schedule

Template = Literal["bigbox_small", "bigbox_mid", "empty", "demo", "tiny"]
ImportKind = Literal["roster", "training", "availability", "forecast", "history",
                     # demand/README.md proposal: corporate labor-model inputs and the demand they produce
                     "labor_model", "labor_standards", "labor_hours", "sales_forecast", "workload"]


class CreateStoreRequest(BaseModel):
    template: str = Field("bigbox_small", pattern=r"^(bigbox_small|bigbox_mid|restaurant_small|empty|demo|tiny|demo_[a-z0-9_]+)$")
    name: Optional[str] = None  # required except for fixture templates (demo, tiny), which keep their own
    jurisdiction: Optional[Jurisdiction] = None


class ImportPreview(BaseModel):
    kind: ImportKind
    columns: list[str]
    proposed_mapping: dict[str, Optional[str]]
    unmapped_required: list[str]
    rows_preview: list[dict[str, Any]]
    row_count: int
    warnings: list[str] = []
    target_fields: list[str] = []    # fields a column can map to for this kind (dropdown options), in order
    required_fields: list[str] = []  # subset of target_fields that must be mapped
    # v1.4 proposal: [{need, any_of: [[field, ...], ...]}]; a need is met when all fields of any alternative
    # are mapped. unmapped_required == the needs not met (e.g. roster "name" is met by first_name + last_name).
    required_any_of: list[dict[str, Any]] = []


class ReadinessCheck(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str
    severity: Literal["ok", "warn", "block"] = "ok"  # v1.5 proposal: warn = show amber, never blocks


class Readiness(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]


class OutreachState(BaseModel):
    plan_id: Optional[str] = None
    status: Literal["idle", "texting", "filled", "exhausted"] = "idle"
    current_rank: Optional[int] = None
    messages: list[Union[OutboundMessage, InboundMessage]] = []
    accepted_employee_ids: list[str] = []
    schedule: Optional[Schedule] = None
    # v1.3 proposal (WS6): how offers go out and whether predictive-scheduling pay is owed
    mode: Literal["one_to_one", "group_offer"] = "one_to_one"  # = FixPlan.outreach_mode
    wave: int = 0                               # how many rounds of offers have gone out
    waiting_employee_ids: list[str] = []        # offered in the current round, no answer yet
    premium: Optional[dict] = None  # {status, law_rule_ids, note, by_employee: [{employee_id, premium_pay_dollars,
    #                                 law_rule_ids, note}]} (by_employee: v1.4 proposal, from the plan's candidates)


class SolveRequest(BaseModel):
    time_limit_s: Optional[float] = Field(None, gt=0, le=120)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    card: Optional[dict[str, Any]] = None


class ChatRequest(BaseModel):
    mode: Literal["onboard", "review", "fix"] = "onboard"
    messages: list[ChatMessage] = []
    # Headless mode only (`?auto_cards=scripted`): card_type -> list of results, consumed in order.
    # {card_type: [result, ...]} answered in order; key "*": "accept_prefill" submits every other card unchanged
    card_script: dict[str, Union[list[dict[str, Any]], Literal["accept_prefill"]]] = {}


class CardSubmission(BaseModel):
    card_id: str
    result: dict[str, Any]
