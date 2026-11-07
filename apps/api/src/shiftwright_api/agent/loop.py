"""One chat turn: LLM -> tool calls -> (cards pause) -> tool results -> LLM ... until no tool calls.

Yields `(event, data)` tuples matching the SSE table in contracts/API.md.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from ..db import Database
from .llm import LLMClient, LLMResponse
from .tools import TOOLS_BY_NAME, CardRequest, ToolContext, ToolResult, specs_for

MAX_STEPS = 40
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

CardWaiter = Callable[[str, str, dict], Awaitable[dict]]  # (card_id, card_type, props) -> result


def system_prompt(mode: str, store_id: str) -> str:
    core = (PROMPTS_DIR / "core.md").read_text()
    mode_file = PROMPTS_DIR / f"{mode}.md"
    extra = mode_file.read_text() if mode_file.exists() else ""
    return f"{core}\n\n{extra}\n\nCurrent mode: {mode}. Store id: {store_id}."


def repair_transcript(messages: list[dict]) -> list[dict]:
    """Ensure every assistant tool_call has a tool result (e.g. after a client disconnect mid-card)."""
    out: list[dict] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        out.append(m)
        i += 1
        ids = [tc["id"] for tc in m.get("tool_calls") or []] if m.get("role") == "assistant" else []
        if ids:
            answered = set()
            while i < len(messages) and messages[i].get("role") == "tool":
                answered.add(messages[i].get("tool_call_id"))
                out.append(messages[i])
                i += 1
            for tid in ids:
                if tid not in answered:
                    out.append({"role": "tool", "tool_call_id": tid,
                                "content": json.dumps({"cancelled": True, "note": "Turn interrupted; nothing applied."})})
    return out


CARD_RESULT_MAX_CHARS = 2000


def _compact(card_result: dict) -> dict:
    """Big card submissions (coverage grids, 60-person training matrices) are applied server-side;
    echoing them back to the model costs tokens and adds nothing. The model can read the config."""
    if len(json.dumps(card_result, default=str)) <= CARD_RESULT_MAX_CHARS:
        return card_result
    return {"submitted": True, "keys": list(card_result)[:20],
            "note": "Large submission applied (see 'changed'); call get_config_summary for details."}


def _summary(name: str, content: dict) -> str:
    if "error" in content:
        return f"{name}: error"
    if content.get("cancelled"):
        return f"{name}: cancelled"
    return f"Ran {name}"


async def run_turn(
    *,
    db: Database,
    llm: LLMClient,
    store_id: str,
    mode: str,
    user_messages: list[dict],
    await_card: CardWaiter,
    aborted: Callable[[], bool] = lambda: False,
) -> AsyncIterator[tuple[str, dict]]:
    transcript = repair_transcript(db.get_transcript(store_id))
    for m in user_messages:
        msg: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        transcript.append(msg)
    db.save_transcript(store_id, transcript)
    ctx = ToolContext(db=db, store_id=store_id)
    tools = specs_for(mode)
    system = {"role": "system", "content": system_prompt(mode, store_id)}

    said = False
    try:
        for _ in range(MAX_STEPS):
            resp: Optional[LLMResponse] = None
            streamed = False
            sep = "\n\n" if said else ""  # keep text from separate steps from running together
            try:
                if hasattr(llm, "stream"):
                    async for piece in llm.stream([system, *transcript], tools):
                        if isinstance(piece, LLMResponse):
                            resp = piece
                        elif piece:
                            streamed = True
                            yield "text", {"delta": sep + piece}
                            sep, said = "", True
                else:
                    resp = await llm.complete([system, *transcript], tools)
            except Exception as e:  # noqa: BLE001 - surfaced to the client
                yield "error", {"message": str(e)}
                return
            if resp is None:
                yield "error", {"message": "The model stream ended without a response."}
                return
            assistant: dict[str, Any] = {"role": "assistant", "content": resp.content or ""}
            if resp.tool_calls:
                assistant["tool_calls"] = [tc.to_openai() for tc in resp.tool_calls]
            transcript.append(assistant)
            if resp.content and not streamed:
                yield "text", {"delta": sep + resp.content}
                said = True
            if not resp.tool_calls:
                break
            for tc in resp.tool_calls:
                tool = TOOLS_BY_NAME.get(tc.name)
                yield "tool", {"name": tc.name, "status": "start", "summary": tc.name}
                result: ToolResult
                if tool is None:
                    result = ToolResult({"error": f"Unknown tool {tc.name!r}"})
                elif isinstance(tc.arguments, str):
                    result = ToolResult({"error": "Tool arguments were not valid JSON.", "raw": tc.arguments[:300]})
                else:
                    try:
                        out = tool.handler(ctx, tc.arguments)
                        if inspect.isawaitable(out):
                            out = await out
                        if isinstance(out, CardRequest):
                            card_id = "card_" + uuid.uuid4().hex[:12]
                            yield "card", {"card_id": card_id, "card_type": out.card_type, "props": out.props}
                            card_result = (await await_card(card_id, out.card_type, out.props) if out.blocking
                                           else {})
                            out = out.apply(card_result)
                            if inspect.isawaitable(out):
                                out = await out
                            if isinstance(out, ToolResult):
                                out.content = {"card_result": _compact(card_result), **out.content}
                        result = out if isinstance(out, ToolResult) else ToolResult(out)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001 - errors go back to the LLM
                        result = ToolResult({"error": f"{type(e).__name__}: {e}"})
                transcript.append({"role": "tool", "tool_call_id": tc.id,
                                   "content": json.dumps(result.content, default=str)})
                db.save_transcript(store_id, transcript)
                if result.patch_summary:
                    yield "config", {"config_version": result.config_version, "patch_summary": result.patch_summary}
                yield "tool", {"name": tc.name, "status": "done", "summary": _summary(tc.name, result.content)}
                if aborted():  # a newer turn took over; remaining tool calls are repaired as cancelled
                    yield "error", {"message": "This turn was replaced by a newer message."}
                    return
        else:
            yield "error", {"message": f"Stopped after {MAX_STEPS} steps without finishing."}
            return
        yield "done", {}
    finally:
        db.save_transcript(store_id, repair_transcript(transcript))


def accept_prefill(card_type: str, props: dict) -> dict:
    """A neutral manager: submit what the card shows, unchanged (WS5 realistic eval)."""
    if card_type == "store_basics":
        return {k: v for k, v in props.items() if k not in ("id", "week_start")}
    if card_type == "payroll":
        return {k: v for k, v in props.items() if k != "approvals"}
    if card_type == "roles":
        return {"departments": props.get("departments", []), "roles": props.get("roles", [])}
    if card_type == "training_matrix":
        return {e["id"]: e.get("trained_role_ids", []) for e in props.get("employees", [])}
    if card_type == "coverage_grid":
        return {"grid": props.get("prefill") or {}}
    if card_type == "department_staffing":
        return {"staffing": props.get("suggested") or {}}
    if card_type == "events":
        return {"events": props.get("events", [])}
    if card_type == "propose_rule":
        c = props.get("constraint") or {}
        if c.get("strength") == "soft":
            return {"decision": "soft", "weight_dollars": c.get("weight_dollars") or 0}
        return {"decision": "hard"}
    if card_type in ("tradeoff", "conflict_menu"):
        opts = props.get("options") or []
        return {"option_id": opts[0]["id"]} if opts else {"cancelled": True}
    if card_type == "confirm_tags":
        return {"decisions": {r["role_id"]: "keep" for r in props.get("roles", [])}}
    if card_type == "employee_availability":
        return {"confirmed": props.get("parsed") or []}
    return {"cancelled": True}  # csv_import (no file headless) and anything unknown


def scripted_waiter(script: dict) -> CardWaiter:
    """Headless mode: answer each card from the script (by card_type, in order). Cards with no scripted
    answer left are cancelled, or, with script {"*": "accept_prefill"}, submitted with their prefill."""
    fallback = script.get("*")
    queues = {k: list(v) for k, v in script.items() if k != "*" and isinstance(v, list)}

    async def wait(card_id: str, card_type: str, props: dict) -> dict:
        q = queues.get(card_type) or []
        if q:
            return q.pop(0)
        if fallback == "accept_prefill":
            return accept_prefill(card_type, props)
        return {"cancelled": True}
    return wait


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def broker_waiter(broker, store_id: str, timeout_s: Optional[float]) -> CardWaiter:
    async def wait(card_id: str, card_type: str, props: dict) -> dict:
        fut = broker.open(store_id, card_id)
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            return {"cancelled": True, "reason": "timeout"}
        finally:
            broker.close(store_id, card_id)
    return wait
