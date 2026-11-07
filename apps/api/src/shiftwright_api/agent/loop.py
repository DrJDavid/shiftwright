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
) -> AsyncIterator[tuple[str, dict]]:
    transcript = repair_transcript(db.get_transcript(store_id))
    for m in user_messages:
        msg: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        transcript.append(msg)
    db.save_transcript(store_id, transcript)
    ctx = ToolContext(db=db, store_id=store_id)
    tools = specs_for(mode)
    system = {"role": "system", "content": system_prompt(mode, store_id)}

    try:
        for _ in range(MAX_STEPS):
            try:
                resp: LLMResponse = await llm.complete([system, *transcript], tools)
            except Exception as e:  # noqa: BLE001 - surfaced to the client
                yield "error", {"message": str(e)}
                return
            assistant: dict[str, Any] = {"role": "assistant", "content": resp.content or ""}
            if resp.tool_calls:
                assistant["tool_calls"] = [tc.to_openai() for tc in resp.tool_calls]
            transcript.append(assistant)
            if resp.content:
                yield "text", {"delta": resp.content}
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
                            card_result = await await_card(card_id, out.card_type, out.props)
                            out = out.apply(card_result)
                            if inspect.isawaitable(out):
                                out = await out
                            if isinstance(out, ToolResult):
                                out.content = {"card_result": card_result, **out.content}
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
        else:
            yield "error", {"message": f"Stopped after {MAX_STEPS} steps without finishing."}
            return
        yield "done", {}
    finally:
        db.save_transcript(store_id, repair_transcript(transcript))


def scripted_waiter(script: dict[str, list[dict]]) -> CardWaiter:
    """Headless mode: answer each card from the script (by card_type, in order); cancel if none left."""
    queues = {k: list(v) for k, v in script.items()}

    async def wait(card_id: str, card_type: str, props: dict) -> dict:
        q = queues.get(card_type) or []
        return q.pop(0) if q else {"cancelled": True}
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
