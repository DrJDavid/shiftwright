"""LLM clients: OpenRouter (real baselines), a disk cache keyed by hash(prompt, model), and the mock.

The OpenRouter client reads OPENROUTER_API_KEY from the environment. It is only constructed when
real baselines are requested; tests use httpx.MockTransport or the mock client.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_TOKENS = 32_000


@dataclass
class ChatResult:
    text: str
    finish_reason: str | None  # "length" means the model hit its output limit (truncated)
    latency_s: float
    model: str
    usage: dict = field(default_factory=dict)
    error: str | None = None


class LLMClient(Protocol):
    async def complete(self, model: str, messages: list[dict]) -> ChatResult: ...


def cache_key(model: str, messages: list[dict]) -> str:
    blob = json.dumps({"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class OpenRouterClient:
    """Plain chat completions, temperature 0, max output tokens as high as the model allows."""

    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 900, base_url: str = OPENROUTER_URL):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.base_url = base_url
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_s, headers={
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/shiftwright",
            "X-Title": "Shiftwright evals",
        })
        self._limits: dict[str, int] | None = None
        self._lock = asyncio.Lock()

    async def max_output_tokens(self, model: str) -> int:
        async with self._lock:
            if self._limits is None:
                self._limits = {}
                try:
                    resp = await self._client.get(f"{self.base_url}/models")
                    for m in resp.json().get("data", []):
                        top = m.get("top_provider") or {}
                        limit = top.get("max_completion_tokens") or m.get("context_length")
                        if isinstance(limit, int) and limit > 0:
                            self._limits[m["id"]] = limit
                except Exception:  # noqa: BLE001 - fall back to the default limit
                    pass
        return self._limits.get(model, DEFAULT_MAX_TOKENS)

    async def complete(self, model: str, messages: list[dict]) -> ChatResult:
        body = {"model": model, "messages": messages, "temperature": 0,
                "max_tokens": await self.max_output_tokens(model)}
        t0 = time.perf_counter()
        try:
            resp = await self._client.post(f"{self.base_url}/chat/completions", json=body)
            latency = round(time.perf_counter() - t0, 2)
            if resp.status_code != 200:
                return ChatResult("", None, latency, model, error=f"HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            if data.get("error"):
                return ChatResult("", None, latency, model, error=json.dumps(data["error"])[:500])
            choice = data["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
            return ChatResult(text, choice.get("finish_reason"), latency, data.get("model", model),
                              usage=data.get("usage") or {})
        except Exception as exc:  # noqa: BLE001 - an API failure is an outcome, not a crash
            return ChatResult("", None, round(time.perf_counter() - t0, 2), model, error=f"{type(exc).__name__}: {exc}")

    async def aclose(self) -> None:
        await self._client.aclose()


class CachedClient:
    """Wraps a client; replays responses stored under hash(prompt, model). Errors are not cached."""

    def __init__(self, inner: LLMClient, cache_dir: Path | None):
        self.inner = inner
        self.cache_dir = cache_dir
        self.hits = 0
        self.misses = 0

    async def complete(self, model: str, messages: list[dict]) -> ChatResult:
        key = cache_key(model, messages)
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            self.hits += 1
            return ChatResult(**json.loads(path.read_text()))
        self.misses += 1
        result = await self.inner.complete(model, messages)
        if path and result.error is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(result)))
        return result


class MockClient:
    """Canned bad outputs (see mock.py). Sees only the prompt, like a real model would."""

    async def complete(self, model: str, messages: list[dict]) -> ChatResult:
        from .mock import respond

        t0 = time.perf_counter()
        text, finish = respond(model, messages)
        return ChatResult(text, finish, round(time.perf_counter() - t0, 2), model)
