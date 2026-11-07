"""API-local helper shapes from contracts/API.md (not in contracts/models.py)."""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from shiftwright_contracts.models import InboundMessage, Jurisdiction, OutboundMessage, Schedule

Template = Literal["bigbox_small", "bigbox_mid", "empty", "demo", "tiny"]
ImportKind = Literal["roster", "training", "availability", "forecast", "history"]


class CreateStoreRequest(BaseModel):
    template: str = Field("bigbox_small", pattern=r"^(bigbox_small|bigbox_mid|empty|demo|tiny|demo_[a-z0-9_]+)$")
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


class ReadinessCheck(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str


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
    card_script: dict[str, list[dict[str, Any]]] = {}


class CardSubmission(BaseModel):
    card_id: str
    result: dict[str, Any]
