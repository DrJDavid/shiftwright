"""Email + password accounts, cookie sessions and store ownership (PUNCHLIST A1).

Passwords: stdlib scrypt, random salt per user. Sessions: 32-byte random token in the `sw_session`
cookie; the db keeps only HMAC-SHA256(AUTH_SECRET, token), so a leaked db can't be replayed as cookies.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .db import Database, EmailTaken, NotFound
from .models import LoginRequest, SignupRequest
from .settings import Settings

COOKIE = "sw_session"
SESSION_DAYS = 30
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)
BAD_LOGIN = "Wrong email or password."
PUBLIC = ("/api/health", "/api/templates", "/api/sms/inbound", "/api/sms/optin")
STORE_PATH = re.compile(r"^/api/stores/([^/]+)")


# ---------------------------------------------------------------- passwords + tokens
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        expected = bytes.fromhex(digest)
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return algo == "scrypt" and hmac.compare_digest(got, expected)


_DUMMY_HASH = hash_password(secrets.token_hex(16))  # unknown emails cost the same scrypt as wrong passwords


def token_key(secret: str, token: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- request helpers
def client_ip(request: Request) -> str:
    """Behind Railway's proxy the socket peer is the proxy, so prefer the proxy's client-IP headers."""
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    fwd = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if fwd:
        return fwd[-1]
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return (proto or request.url.scheme) == "https"


class RateLimiter:
    """At most `limit` hits per key in a rolling `window_s` (in memory; resets on restart)."""

    def __init__(self, limit: int = 10, window_s: float = 600, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


# ---------------------------------------------------------------- wiring
def current_user(request: Request) -> Optional[dict]:
    return getattr(request.state, "user", None)


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


def is_public(path: str) -> bool:
    return path in PUBLIC or path.startswith("/api/auth/") or not path.startswith("/api/")


def install(app: FastAPI, settings: Settings, db: Callable[[], Database]) -> None:
    """Session middleware (+ ownership guard when AUTH_REQUIRED) and the /api/auth routes."""
    limiter = RateLimiter()

    @app.middleware("http")
    async def sessions(request: Request, call_next):
        path = request.url.path
        token = request.cookies.get(COOKIE)
        request.state.user = db().session_user(token_key(settings.auth_secret, token)) if token else None
        if settings.auth_required and not is_public(path):
            user = request.state.user
            if user is None:
                return JSONResponse({"detail": "Sign in first."}, status_code=401)
            m = STORE_PATH.match(path)
            if m:
                sid = m.group(1)
                try:
                    owner = db().store_owner(sid)
                except NotFound:
                    owner = None
                if owner != user["id"]:  # someone else's store looks exactly like a missing one
                    return JSONResponse({"detail": f"Store {sid!r} not found"}, status_code=404)
        return await call_next(request)

    def start_session(request: Request, response: Response, user: dict) -> None:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        db().create_session(token_key(settings.auth_secret, token), user["id"], expires)
        response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, path="/", httponly=True, samesite="lax",
                            secure=is_https(request))

    def limit(request: Request) -> None:
        if not limiter.hit(client_ip(request)):
            raise HTTPException(429, "Too many sign-in attempts; try again in a few minutes.",
                                headers={"Retry-After": str(int(limiter.window_s))})

    router = APIRouter()

    @router.post("/api/auth/signup")
    def signup(body: SignupRequest, request: Request, response: Response) -> dict:
        limit(request)
        try:
            user = db().create_user("u_" + uuid.uuid4().hex[:12], body.email.strip(), body.name.strip(),
                                    hash_password(body.password))
        except EmailTaken:
            raise HTTPException(409, "An account with that email already exists.")
        start_session(request, response, user)
        return {"user": user}

    @router.post("/api/auth/login")
    def login(body: LoginRequest, request: Request, response: Response) -> dict:
        limit(request)
        row = db().user_by_email(body.email.strip())
        ok = verify_password(body.password, row["pw_hash"] if row else _DUMMY_HASH)
        if not (row and ok):
            raise HTTPException(401, BAD_LOGIN)
        user = {k: row[k] for k in ("id", "email", "name")}
        start_session(request, response, user)
        return {"user": user}

    @router.post("/api/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        token = request.cookies.get(COOKIE)
        if token:
            db().delete_session(token_key(settings.auth_secret, token))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=is_https(request))
        return response

    @router.get("/api/auth/me")
    def me(request: Request) -> dict:
        return {"user": require_user(request)}

    app.include_router(router)
