"""Smoke test a running API: health -> sign up (when accounts are on) -> create store (demo fixture if
present) -> readiness -> solve.

    uv run python apps/api/scripts/smoke.py [BASE_URL]      # default http://localhost:8000
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]
FIXTURES = [REPO / "packages/scenarios/fixtures/demo_store.json", REPO / "packages/scenarios/fixtures/tiny_store.json"]


def main(base: str) -> int:
    c = httpx.Client(base_url=base, timeout=120)
    h = c.get("/api/health").raise_for_status().json()
    print("health:", h)
    if h.get("auth_required", True):
        email = f"smoke+{secrets.token_hex(4)}@example.com"
        u = c.post("/api/auth/signup", json={"email": email, "password": secrets.token_urlsafe(12),
                                             "name": "Smoke Test"}).raise_for_status().json()["user"]
        print("signed up:", u["email"])
    cfg = c.post("/api/stores", json={"name": "Store #0417", "jurisdiction": {"state": "TX", "city": "austin"},
                                      "template": "bigbox_mid"}).raise_for_status().json()
    sid = cfg["store"]["id"]
    fixture = next((f for f in FIXTURES if f.exists()), None)
    if fixture:
        data = json.loads(fixture.read_text())
        data["store"]["id"] = sid
        c.put(f"/api/stores/{sid}/config", json=data).raise_for_status()
        print(f"loaded {fixture.name} into {sid}")
    rd = c.get(f"/api/stores/{sid}/readiness").raise_for_status().json()
    print("ready:", rd["ready"], [x["id"] for x in rd["checks"] if not x["ok"]])
    r = c.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 30})
    print("solve:", r.status_code)
    if r.status_code == 200:
        s = r.json()
        print("  status:", s["schedule"]["status"], "by", s["schedule"]["produced_by"],
              "| shifts:", len(s["schedule"]["shifts"]), "| gaps:", len(s["schedule"]["gaps"]),
              "| validation passed:", s["validation"]["passed"])
    else:
        print("  ", r.text[:300])
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
