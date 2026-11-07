"""End-to-end demo outreach on the demo store with the scripted mock replies.

solve -> /fix for the Saturday 06:04 call-outs (demo_scenario.json) -> /outreach/start -> /outreach/stream
until the outreach finishes. Prints timings and the phone thread.

    uv run python apps/api/scripts/demo_outreach.py                 # in-process app (temp DB)
    uv run python apps/api/scripts/demo_outreach.py http://host:8016 # against a running API (needs MESSENGER=mock)

Exits 2 (skip) if the engine's fix_day has not landed yet.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCENARIO = REPO / "packages/scenarios/fixtures/demo_scenario.json"


@contextmanager
def client(base: str | None, reply_delay_s: float):
    if base:
        import httpx
        with httpx.Client(base_url=base, timeout=180, headers={"X-Demo-Key": os.environ.get("DEMO_KEY", "")}) as c:
            yield c
        return
    from fastapi.testclient import TestClient
    from shiftwright_api.main import create_app
    from shiftwright_api.settings import Settings
    s = Settings(database_url=f"sqlite:///{tempfile.mkdtemp()}/demo.db", messenger="mock",
                 mock_autoreply="script", mock_reply_delay_s=reply_delay_s, outreach_timeout_s=60)
    with TestClient(create_app(settings=s)) as c:
        yield c


def run(base: str | None = None, reply_delay_s: float = 4.0) -> dict:
    """Returns timings + final state. Raises SystemExit(2) when fix_day isn't available."""
    scenario = json.loads(SCENARIO.read_text())
    callouts = scenario["callout_events"]
    out: dict = {}
    with client(base, reply_delay_s) as c:
        health = c.get("/api/health").json()
        if "engine.fix_day" in health.get("stubs", []):
            print("SKIP: engine.fix_day has not landed (stubbed).")
            raise SystemExit(2)
        sid = c.post("/api/stores", json={"template": "demo"}).json()["store"]["id"]
        t = time.time()
        r = c.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 30})
        out["solve_s"] = round(time.time() - t, 2)
        assert r.status_code == 200, r.text
        sched = r.json()["schedule"]
        print(f"solve: {out['solve_s']}s, {len(sched['shifts'])} shifts, coverage {sched['metrics']['coverage_pct']:.1f}%")

        t = time.time()
        r = c.post(f"/api/stores/{sid}/fix", json={"callouts": callouts, "day": callouts[0]["day"],
                                                   "now": callouts[0]["reported_at"]})
        out["fix_s"] = round(time.time() - t, 2)
        assert r.status_code == 200, r.text
        plan = r.json()
        print(f"fix: {out['fix_s']}s, {len(plan['actions'])} actions, {len(plan['outreach_queue'])} in queue, "
              f"coverage {plan['coverage_before_pct']:.1f}% -> best {plan['coverage_after_best_pct']:.1f}%")

        t0 = time.time()
        r = c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]})
        assert r.status_code == 200, r.text
        first_text = None
        last = None
        with c.stream("GET", f"/api/stores/{sid}/outreach/stream") as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                last = json.loads(line[6:])
                if first_text is None and any(m.get("to_employee_id") for m in last["messages"]):
                    first_text = round(time.time() - t0, 2)
        out["first_text_s"] = first_text
        out["outreach_s"] = round(time.time() - t0, 2)
        out["status"] = last["status"]
        out["accepted"] = last["accepted_employee_ids"]
        out["messages"] = len(last["messages"])
        print(f"outreach: {last['status']} in {out['outreach_s']}s (first text {first_text}s), "
              f"accepted {last['accepted_employee_ids']}")
        for m in last["messages"]:
            who = f"-> {m['to_employee_id']}" if m.get("to_employee_id") else f"<- {m['from_phone']}"
            print(f"   {(m.get('sent_at') or m.get('received_at'))[11:19]} {who}: {m['body']}")
        if last.get("schedule"):
            print(f"   final coverage {last['schedule']['metrics']['coverage_pct']:.1f}%")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    delay = float(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--delay=")), 4))
    res = run(args[0] if args else None, delay)
    sys.exit(0 if res["status"] == "filled" else 1)
