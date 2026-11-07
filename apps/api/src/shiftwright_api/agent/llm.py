"""LLM clients. OpenRouter (OpenAI-compatible tool calling) for real; FakeLLM for tests and evals."""
from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Union

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Union[dict, str]  # str when the model sent JSON we could not parse

    def to_openai(self) -> dict:
        args = self.arguments if isinstance(self.arguments, str) else json.dumps(self.arguments)
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": args}}


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMUnavailable(RuntimeError):
    pass


class LLMClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, timeout_s: float = 120.0):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if not self.api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY is not set; the chat agent is unavailable.")
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "X-Title": "Shiftwright"},
                json=body,
            )
        if r.status_code >= 400:
            raise LLMUnavailable(f"OpenRouter error {r.status_code}: {r.text[:500]}")
        data = r.json()
        if "choices" not in data or not data["choices"]:
            raise LLMUnavailable(f"OpenRouter returned no choices: {str(data)[:500]}")
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                args: Union[dict, str] = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = raw
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
        return LLMResponse(content=msg.get("content") or None, tool_calls=calls)


# --------------------------------------------------------------------------- #
# Fake LLM for tests / headless evals
# --------------------------------------------------------------------------- #
Step = Union[LLMResponse, Callable[[list[dict]], LLMResponse]]
_ids = itertools.count(1)


def call(name: str, **arguments: Any) -> LLMResponse:
    """One assistant step that calls a single tool."""
    return LLMResponse(tool_calls=[ToolCall(id=f"call_{next(_ids)}", name=name, arguments=arguments)])


def calls(*steps: LLMResponse) -> LLMResponse:
    """Merge several `call(...)` steps into one assistant message with parallel tool calls."""
    return LLMResponse(tool_calls=[tc for s in steps for tc in s.tool_calls])


def say(text: str) -> LLMResponse:
    return LLMResponse(content=text)


class FakeLLM:
    """Replays a script of steps. Records every `messages` list it was called with in `.calls`."""

    def __init__(self, steps: list[Step] | None = None):
        self._steps: list[Step] = list(steps or [])
        self.calls: list[list[dict]] = []
        self.tools_seen: list[str] = []

    def script(self, steps: list[Step]) -> None:
        self._steps.extend(steps)

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))
        self.tools_seen = [t["function"]["name"] for t in tools]
        if not self._steps:
            return LLMResponse(content=None)
        step = self._steps.pop(0)
        return step(messages) if callable(step) else step
