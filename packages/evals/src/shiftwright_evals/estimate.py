"""Estimate the OpenRouter cost of a real baseline run, from the actual prompts. No API key needed.

    uv run python -m shiftwright_evals.estimate [--quick] [--models a,b,c] [--reasoning-x 2]

Prompt tokens = prompt characters / CHARS_PER_TOKEN (JSON-heavy text tokenizes at roughly 3 chars per
token; this is an approximation, not a tokenizer). Output tokens = the size of a complete answer
(the engine's schedule from the eval cache if present, else the mock greedy schedule, compact JSON) ×
(1 + reasoning multiplier) for hidden reasoning tokens, capped at the model's max completion tokens.
Prices come live from the public https://openrouter.ai/api/v1/models endpoint.
"""
from __future__ import annotations

import argparse
import json
import os

import httpx

from . import mock, prompts
from .suites import REPAIR_NOW, build_cases

CHARS_PER_TOKEN = 3.0
DEFAULT_MODELS = "x-ai/grok-4.7,anthropic/claude-opus-5.5,openai/gpt-6.1-terra-pro"


def fetch_models() -> dict[str, dict]:
    data = httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]
    return {m["id"]: m for m in data}


def price(model: dict, prompt_tokens: float) -> tuple[float, float]:
    p = model["pricing"]
    inp, out = float(p["prompt"]), float(p["completion"])
    for o in p.get("overrides") or []:
        if prompt_tokens >= o.get("min_prompt_tokens", 1e18):
            inp, out = float(o.get("prompt", inp)), float(o.get("completion", out))
    return inp, out


def case_sizes(quick: bool) -> list[dict]:
    rows = []
    for case in build_cases(["weekly", "honesty", "repair"], quick):
        cfg = case.config
        greedy = mock._schedule(cfg.model_dump(mode="json"), mock.greedy(cfg.model_dump(mode="json")))
        answer_chars = len(json.dumps(greedy, separators=(",", ":")))
        if case.suite == "repair":
            base = case.scenario.history[-1]
            msgs = prompts.repair_messages(cfg, base, case.scenario.callout_events, case.scenario.expected["callout_day"], REPAIR_NOW)
            answer_chars = len(base.model_dump_json()) + 500
        else:
            msgs = prompts.weekly_messages(cfg)
        rows.append({"scenario": case.scenario_id, "size": case.size,
                     "prompt_chars": len(prompts.render(msgs)), "answer_chars": answer_chars})
    return rows


def realistic_sizes(quick: bool) -> list[dict]:
    """Chat prompts exactly as sent (narrative + CSVs). Answer = a CSV line per shift of a sloppy full
    schedule (mock greedy, ~40 chars/line) + ~3,000 chars of prose and assumptions."""
    from .realistic import chat_messages, export_texts, realistic_cases
    rows = []
    for case in realistic_cases(quick):
        cfg = case.config.model_dump(mode="json")
        n_shifts = len(mock.greedy(cfg))
        rows.append({"scenario": case.scenario_id, "size": case.size,
                     "prompt_chars": len(prompts.render(chat_messages(case, export_texts(case)))),
                     "answer_chars": n_shifts * 40 + 3000})
    return rows


# Shiftwright intake agent (AGENT_MODEL, default anthropic/claude-sonnet-5.5): an assumption, not a measurement.
INTAKE_CALLS_PER_STORE = 30
INTAKE_PROMPT_TOKENS_PER_CALL = 25_000
INTAKE_OUTPUT_TOKENS_PER_CALL = 800


def estimate(quick: bool, models: list[str], reasoning_x: float, catalog: dict | None = None,
             suite: str = "solver") -> dict:
    catalog = catalog or fetch_models()
    sizes = realistic_sizes(quick) if suite == "realistic" else case_sizes(quick)
    out = {"scenarios": len(sizes), "chars_per_token": CHARS_PER_TOKEN, "reasoning_x": reasoning_x, "models": {}}
    for mid in models:
        m = catalog.get(mid)
        if m is None:
            out["models"][mid] = {"error": "not in the OpenRouter catalog"}
            continue
        cap = (m.get("top_provider") or {}).get("max_completion_tokens") or 32000
        total_in = total_out = cost = 0.0
        truncated = 0
        for s in sizes:
            pt = s["prompt_chars"] / CHARS_PER_TOKEN
            ot = s["answer_chars"] / CHARS_PER_TOKEN * (1 + reasoning_x)
            if ot > cap:
                truncated += 1
                ot = cap
            pi, po = price(m, pt)
            total_in += pt
            total_out += ot
            cost += pt * pi + ot * po
        out["models"][mid] = {"prompt_tokens": round(total_in), "output_tokens": round(total_out),
                              "usd": round(cost, 2), "max_completion_tokens": cap,
                              "likely_truncated": truncated,
                              "price_per_mtok": [round(float(m["pricing"]["prompt"]) * 1e6, 3),
                                                 round(float(m["pricing"]["completion"]) * 1e6, 3)]}
    if suite == "realistic":
        agent = os.environ.get("AGENT_MODEL") or "anthropic/claude-sonnet-5.5"
        m = catalog.get(agent)
        if m:
            pt = INTAKE_CALLS_PER_STORE * INTAKE_PROMPT_TOKENS_PER_CALL * len(sizes)
            ot = INTAKE_CALLS_PER_STORE * INTAKE_OUTPUT_TOKENS_PER_CALL * len(sizes)
            pi, po = price(m, INTAKE_PROMPT_TOKENS_PER_CALL)
            out["models"][f"intake agent ({agent})"] = {
                "prompt_tokens": pt, "output_tokens": ot, "usd": round(pt * pi + ot * po, 2),
                "assumption": f"{INTAKE_CALLS_PER_STORE} agent calls/store × {INTAKE_PROMPT_TOKENS_PER_CALL} prompt "
                              f"+ {INTAKE_OUTPUT_TOKENS_PER_CALL} output tokens (not measured)"}
    out["total_usd"] = round(sum(v.get("usd", 0) for v in out["models"].values()), 2)
    by_size: dict[str, list] = {}
    for s in sizes:
        by_size.setdefault(s["size"], []).append(s)
    out["per_size_tokens"] = {k: {"prompt": round(max(x["prompt_chars"] for x in v) / CHARS_PER_TOKEN),
                                  "answer": round(max(x["answer_chars"] for x in v) / CHARS_PER_TOKEN)}
                              for k, v in sorted(by_size.items())}
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shiftwright_evals.estimate")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--suite", choices=["solver", "realistic"], default="solver")
    p.add_argument("--models", default=os.environ.get("BASELINE_MODELS") or DEFAULT_MODELS)
    p.add_argument("--reasoning-x", type=float, default=2.0,
                   help="hidden reasoning tokens as a multiple of the visible answer (billed as output)")
    a = p.parse_args(argv)
    print(json.dumps(estimate(a.quick, [m.strip() for m in a.models.split(",") if m.strip()], a.reasoning_x,
                              suite=a.suite), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
