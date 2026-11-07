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
    sms_allowlist: list[str] = field(default_factory=list)  # SMS_ALLOWLIST + DEMO_PHONE_1/2; Twilio texts only these
    demo_key: str = ""  # DEMO_KEY: if set, mutating /api/stores* routes need header X-Demo-Key
    max_texts_per_store_hour: int = 20
    mock_autoreply: str = "off"  # off | script | prob (from_env: default "script" when MESSENGER=mock)
    mock_reply_delay_s: float = 4.0
    mock_seed: int = 417
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
            sms_allowlist=[p.strip() for p in ",".join(
                [env("SMS_ALLOWLIST") or "", env("DEMO_PHONE_1") or "", env("DEMO_PHONE_2") or ""]).split(",")
                if p.strip()],
            demo_key=(env("DEMO_KEY") or "").strip(),
            max_texts_per_store_hour=int(env("MAX_TEXTS_PER_STORE_HOUR") or 20),
            mock_autoreply=(env("MOCK_AUTOREPLY") or "script").strip().lower(),
            mock_reply_delay_s=float(env("MOCK_REPLY_DELAY_S") or 4),
            mock_seed=int(env("MOCK_SEED") or 417),
        )

    @property
    def sqlite_path(self) -> str:
        url = self.database_url
        if not url.startswith("sqlite:///"):
            raise ValueError(f"Only sqlite:/// DATABASE_URLs are supported, got {url!r}")
        return url[len("sqlite:///"):]
