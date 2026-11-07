"""Systems under test: the Shiftwright engine and the chat-model baselines.

Each system turns a case into an `Output`: the exact prompt (or call), the raw output, and the thing
to hand to the validator. Systems never score anything themselves.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from shiftwright_contracts.models import CallOut, FixRequest, Schedule, StoreConfig

from . import prompts
from .llm import ChatResult, LLMClient


@dataclass
class Output:
    prompt_text: str
    raw_text: str = ""
    schedule_input: Any = None  # dict or text for validate_raw; None = nothing usable
    outcome: str = "ok"         # ok | unparseable | truncated | error | unavailable
    latency_s: float | None = None
    attempts: list[dict] = field(default_factory=list)
    call_list: list | None = None
    note: str = ""
    extra_files: dict[str, str] = field(default_factory=dict)


def extract_json(text: str) -> tuple[dict | None, str]:
    """Find the JSON object in a chat reply: whole text, a ``` fence (last first), or first { .. last }."""
    text = (text or "").strip()
    candidates = [text]
    candidates += [m.strip() for m in reversed(re.findall(r"```(?:json)?\s*(.*?)```", text, re.S))]
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first:last + 1])
    err = "no JSON object found"
    for c in candidates:
        try:
            data = json.loads(c)
        except (ValueError, RecursionError) as exc:
            err = f"invalid JSON: {str(exc)[:120]}"
            continue
        if isinstance(data, dict):
            return data, ""
        err = f"top-level JSON is a {type(data).__name__}, not an object"
    return None, err


# --------------------------------------------------------------------------- #
# Shiftwright (the engine)
# --------------------------------------------------------------------------- #
def _engine_module():
    try:
        return import_module("shiftwright_engine")
    except ImportError:
        return None


def engine_source_hash(mod) -> str:
    root = Path(mod.__file__).parent
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


class ShiftwrightSystem:
    """Calls shiftwright_engine lazily. Results are cached by hash(engine source, inputs), so a re-run
    with an unchanged engine reproduces the same report."""

    name = "shiftwright"

    def __init__(self, enabled: bool = True, time_limit_s: float | dict = 30, fix_time_limit_s: float = 10,
                 cache_dir: Path | None = None, workers: int = 1):
        self.mod = _engine_module() if enabled else None
        self.time_limit_s = time_limit_s
        self.fix_time_limit_s = fix_time_limit_s
        self.cache_dir = cache_dir
        self.sem = asyncio.Semaphore(workers)
        self.hits = 0
        self.misses = 0
        self.src_hash = engine_source_hash(self.mod) if self.mod else None
        if not enabled:
            self.unavailable_reason = "engine disabled (--no-engine)"
        elif self.mod is None:
            self.unavailable_reason = "shiftwright_engine is not installed on this branch"
        elif not hasattr(self.mod, "solve_week"):
            self.unavailable_reason = "shiftwright_engine has no solve_week"
        else:
            self.unavailable_reason = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def can_fix(self) -> bool:
        return self.available and hasattr(self.mod, "fix_day")

    async def _cached(self, kind: str, payload: str, fn) -> tuple[str, float]:
        key = hashlib.sha256(f"{self.src_hash}|{kind}|{payload}".encode()).hexdigest()
        path = self.cache_dir / "engine" / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            self.hits += 1
            d = json.loads(path.read_text())
            return d["output"], d["latency_s"]
        self.misses += 1
        async with self.sem:
            t0 = time.perf_counter()
            out = await asyncio.to_thread(fn)
            latency = round(time.perf_counter() - t0, 2)
        text = out.model_dump_json()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"output": text, "latency_s": latency}))
        return text, latency

    def limit_for(self, config: StoreConfig) -> float:
        """Per-size solve time limit (S <= 40 staff, M <= 80, else L) when given as a dict."""
        if not isinstance(self.time_limit_s, dict):
            return float(self.time_limit_s)
        n = len(config.employees)
        size = "S" if n <= 40 else "M" if n <= 80 else "L"
        return float(self.time_limit_s.get(size, max(self.time_limit_s.values())))

    async def _solve_text(self, config: StoreConfig) -> tuple[str, float]:
        tl = self.limit_for(config)
        return await self._cached(f"solve_week|{tl}", config.model_dump_json(),
                                  lambda: self.mod.solve_week(config, time_limit_s=tl))

    async def solve(self, config: StoreConfig) -> tuple[Schedule, float]:
        text, latency = await self._solve_text(config)
        return Schedule.model_validate_json(text), latency

    async def weekly(self, config: StoreConfig) -> Output:
        call = (f"shiftwright_engine.solve_week(config, time_limit_s={self.limit_for(config):g})\n"
                "config: _inputs/<scenario>/config.json\n")
        if not self.available:
            return Output(call, outcome="unavailable", note=self.unavailable_reason)
        try:
            text, latency = await self._solve_text(config)
        except Exception as exc:  # noqa: BLE001 - an engine crash is a reported outcome
            return Output(call, raw_text=f"{type(exc).__name__}: {exc}", outcome="error", note="engine raised")
        return Output(call, raw_text=text, schedule_input=json.loads(text), latency_s=latency)

    async def repair(self, config: StoreConfig, schedule: Schedule, callouts: list[CallOut], day: int, now: int) -> Output:
        call = (f"shiftwright_engine.fix_day(FixRequest(config, schedule, callouts, day={day}, now={now}), "
                f"time_limit_s={self.fix_time_limit_s}) -> FixPlan.schedule_if_all_accept\n"
                "inputs: _inputs/<scenario>/{config,base_schedule,callouts}.json\n")
        if not self.can_fix:
            return Output(call, outcome="unavailable",
                          note=self.unavailable_reason or "shiftwright_engine has no fix_day yet")
        req = FixRequest(config=config, schedule=schedule, callouts=callouts, day=day, now=now)
        try:
            text, latency = await self._cached(
                f"fix_day|{self.fix_time_limit_s}", req.model_dump_json(),
                lambda: self.mod.fix_day(req, time_limit_s=self.fix_time_limit_s))
        except Exception as exc:  # noqa: BLE001
            return Output(call, raw_text=f"{type(exc).__name__}: {exc}", outcome="error", note="fix_day raised")
        plan = json.loads(text)
        call_list = [{"rank": c["rank"], "employee_id": c["employee_id"],
                      "role_id": (c["proposed_shift"]["segments"] or [{}])[0].get("role_id"),
                      "start": c["proposed_shift"]["start"], "end": c["proposed_shift"]["end"], "why": c["why"]}
                     for c in plan.get("outreach_queue", [])]
        return Output(call, raw_text=text, schedule_input=plan["schedule_if_all_accept"], latency_s=latency,
                      call_list=call_list)


# --------------------------------------------------------------------------- #
# Baselines (plain chat, same inputs)
# --------------------------------------------------------------------------- #
class BaselineSystem:
    def __init__(self, model: str, client: LLMClient, mock: bool = False):
        self.model = model
        self.client = client
        self.mock = mock
        self.name = f"baseline:{model}"
        self.available = True
        self.unavailable_reason = None

    async def _ask(self, messages: list[dict], want_wrapper: bool) -> Output:
        attempts: list[dict] = []
        raws: list[str] = []
        latency = 0.0
        res: ChatResult | None = None
        data = None
        for attempt in range(2):  # one retry on unparseable JSON
            res = await self.client.complete(self.model, messages)
            latency += res.latency_s
            raws.append(res.text)
            attempts.append({"finish_reason": res.finish_reason, "latency_s": res.latency_s,
                             "chars": len(res.text), "usage": res.usage, "error": res.error})
            if res.error:
                break
            data, err = extract_json(res.text)
            if data is not None and want_wrapper and not isinstance(data.get("schedule"), dict) and "shifts" not in data:
                data, err = None, "no 'schedule' object in the reply"
            if data is not None or res.finish_reason == "length" or attempt == 1:
                break
            messages = messages + [{"role": "assistant", "content": res.text},
                                   {"role": "user", "content": prompts.RETRY.format(error=err)}]
        out = Output(prompts.render(messages), raw_text=raws[-1], latency_s=round(latency, 2), attempts=attempts)
        if len(raws) > 1:
            out.extra_files["raw_output.attempt1.txt"] = raws[0]
        if res.error:
            out.outcome, out.note = "error", res.error
            return out
        if res.finish_reason == "length":
            out.outcome = "truncated"
        elif data is None:
            out.outcome = "unparseable"
        if data is None:
            out.schedule_input = res.text  # the validator reports exactly why it can't be read
            return out
        if want_wrapper and isinstance(data.get("schedule"), dict):
            out.call_list = data.get("call_list") if isinstance(data.get("call_list"), list) else []
            data = data["schedule"]
        out.schedule_input = data
        return out

    async def weekly(self, config: StoreConfig) -> Output:
        return await self._ask(prompts.weekly_messages(config), want_wrapper=False)

    async def repair(self, config: StoreConfig, schedule: Schedule, callouts: list[CallOut], day: int, now: int) -> Output:
        return await self._ask(prompts.repair_messages(config, schedule, callouts, day, now), want_wrapper=True)
