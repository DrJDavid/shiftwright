"""Messenger interface (mock | twilio) and reply interpretation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional, Protocol

import httpx

from shiftwright_contracts.models import Employee, OutboundMessage

from .agent.llm import LLMClient

Interpretation = Literal["accept", "decline", "question", "unknown"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Messenger(Protocol):
    name: str

    async def send(self, employee: Employee, body: str, outreach_rank: Optional[int] = None) -> OutboundMessage: ...


class MockMessenger:
    """Stores messages in memory. Replies arrive through POST /api/sms/mock-reply."""

    name = "mock"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, employee: Employee, body: str, outreach_rank: Optional[int] = None) -> OutboundMessage:
        msg = OutboundMessage(id="out_" + uuid.uuid4().hex[:10], to_employee_id=employee.id, to_phone=employee.phone,
                              body=body, sent_at=_now(), outreach_rank=outreach_rank)
        self.sent.append(msg)
        return msg


class TwilioMessenger:
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        if not (account_sid and auth_token and from_number):
            raise ValueError("MESSENGER=twilio needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER.")
        self.sid, self.token, self.from_number = account_sid, auth_token, from_number

    async def send(self, employee: Employee, body: str, outreach_rank: Optional[int] = None) -> OutboundMessage:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, auth=(self.sid, self.token),
                                  data={"From": self.from_number, "To": employee.phone, "Body": body})
        if r.status_code >= 400:
            raise RuntimeError(f"Twilio send failed {r.status_code}: {r.text[:300]}")
        sid = r.json().get("sid") or uuid.uuid4().hex[:10]
        return OutboundMessage(id=f"tw_{sid}", to_employee_id=employee.id, to_phone=employee.phone, body=body,
                               sent_at=_now(), outreach_rank=outreach_rank)


def twilio_signature_valid(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    """Twilio request validation: base64(HMAC-SHA1(token, url + sorted(k+v)))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def make_messenger(settings) -> Messenger:
    if settings.messenger == "twilio":
        return TwilioMessenger(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from_number)
    return MockMessenger()


# --------------------------------------------------------------------------- #
_ACCEPT = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "k", "i can", "can do", "on my way", "omw",
           "sounds good", "absolutely", "definitely", "will do", "i'm in", "im in", "count me in"}
_DECLINE = {"no", "n", "nope", "nah", "can't", "cant", "cannot", "can not", "sorry", "not today", "busy",
            "no thanks", "no thank you", "pass", "unable", "i can't", "i cant"}


def interpret_keywords(body: str) -> Optional[Interpretation]:
    text = body.strip().lower()
    clean = re.sub(r"[^a-z' ]+", " ", text).strip()
    first = clean.split(" ")[0] if clean else ""
    if clean in _ACCEPT or (first in {"yes", "y", "yeah", "yep", "sure", "ok", "okay"} and "?" not in text):
        return "accept"
    if clean in _DECLINE or first in {"no", "nope", "nah", "sorry"} or any(
            p in clean for p in ("can't", "cant ", "cannot", "not able", "unable")):
        return "decline"
    if text.endswith("?"):
        return "question"
    return None


async def interpret(body: str, llm: Optional[LLMClient]) -> Interpretation:
    hit = interpret_keywords(body)
    if hit:
        return hit
    if llm is None:
        return "unknown"
    try:
        resp = await llm.complete([{"role": "user", "content": (
            "An employee was texted an offer to pick up a shift and replied:\n"
            f"{json.dumps(body)}\n"
            "Classify the reply as exactly one word: accept, decline, question, or unknown.")}], [])
        word = (resp.content or "").strip().lower().split()[0].strip(".,!\"'")
        return word if word in ("accept", "decline", "question", "unknown") else "unknown"  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        return "unknown"
