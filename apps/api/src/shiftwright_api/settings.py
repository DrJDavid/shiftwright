"""Environment-driven settings (see .env.example and contracts/API.md)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_AGENT_MODEL = "anthropic/claude-sonnet-5.5"  # override with AGENT_MODEL


@dataclass
class Settings:
    database_url: str = "sqlite:///./shiftwright.db"
    messenger: str = "mock"
    agent_model: str = DEFAULT_AGENT_MODEL
    openrouter_api_key: str = ""
    public_base_url: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    outreach_timeout_s: float = 90.0
    card_timeout_s: float = 30 * 60
    web_dist: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            database_url=env("DATABASE_URL") or "sqlite:///./shiftwright.db",
            messenger=(env("MESSENGER") or "mock").strip().lower(),
            agent_model=env("AGENT_MODEL") or DEFAULT_AGENT_MODEL,
            openrouter_api_key=env("OPENROUTER_API_KEY") or "",
            public_base_url=env("PUBLIC_BASE_URL") or "",
            twilio_account_sid=env("TWILIO_ACCOUNT_SID") or "",
            twilio_auth_token=env("TWILIO_AUTH_TOKEN") or "",
            twilio_from_number=env("TWILIO_FROM_NUMBER") or "",
            outreach_timeout_s=float(env("OUTREACH_TIMEOUT_S") or 90),
            web_dist=env("WEB_DIST") or "",
        )

    @property
    def sqlite_path(self) -> str:
        url = self.database_url
        if not url.startswith("sqlite:///"):
            raise ValueError(f"Only sqlite:/// DATABASE_URLs are supported, got {url!r}")
        return url[len("sqlite:///"):]
