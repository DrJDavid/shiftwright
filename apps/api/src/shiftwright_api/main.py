"""Shiftwright API (WS6). Implements contracts/API.md. Run: uvicorn shiftwright_api.main:app"""
from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from shiftwright_contracts.models import (
    CONTRACT_VERSION,
    CallOut,
    FixPlan,
    FixRequest,
    Gap,
    Jurisdiction,
    LawPack,
    Schedule,
    StoreConfig,
    ValidationReport,
)

from . import imports, integrations, readiness, templates
from .agent.cards import CardBroker
from .agent.llm import LLMClient, OpenRouterClient
from .agent.loop import broker_waiter, run_turn, scripted_waiter, sse
from .agent.tools import with_law
from .db import ConfigInvalid, Database, NotFound
from .explain import phrase_gap
from .messenger import MockMessenger, make_messenger, twilio_signature_valid
from .models import (
    CardSubmission,
    ChatRequest,
    CreateStoreRequest,
    ImportKind,
    ImportPreview,
    OutreachState,
    Readiness,
    SolveRequest,
)
from .outreach import OutreachBusy, OutreachManager
from .settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]


def create_app(settings: Optional[Settings] = None, llm: Optional[LLMClient] = None,
               helper_llm: Optional[LLMClient] = None) -> FastAPI:
    """`llm` drives the chat agent. `helper_llm` does one-shot jobs (CSV column mapping, SMS reply
    fallback); by default it is the OpenRouter client when a key is set, else None (heuristics only)."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Shiftwright API", version=CONTRACT_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.sqlite_path)
    app.state.llm = llm or OpenRouterClient(settings.openrouter_api_key, settings.agent_model)
    app.state.cards = CardBroker()
    app.state.turn_locks = {}
    if helper_llm is None and settings.openrouter_api_key:
        helper_llm = OpenRouterClient(settings.openrouter_api_key, settings.agent_model)
    app.state.helper_llm = helper_llm
    startup_warnings: list[str] = []
    try:
        messenger = make_messenger(settings)
    except ValueError as e:
        startup_warnings.append(f"{e} Falling back to MESSENGER=mock.")
        messenger = MockMessenger()
    app.state.messenger = messenger
    app.state.outreach = OutreachManager(app.state.db, messenger, helper_llm, settings.outreach_timeout_s,
                                         settings.max_texts_per_store_hour)

    if settings.demo_key:
        @app.middleware("http")
        async def require_demo_key(request: Request, call_next):
            path = request.url.path
            guarded = path.startswith("/api/stores") or path == "/api/sms/mock-reply"
            if (guarded and request.method not in ("GET", "HEAD", "OPTIONS")
                    and not hmac.compare_digest(request.headers.get("X-Demo-Key", ""), settings.demo_key)):
                return JSONResponse({"detail": "Missing or wrong X-Demo-Key header."}, status_code=401)
            return await call_next(request)

    def db() -> Database:
        return app.state.db

    def load(store_id: str) -> StoreConfig:
        try:
            return db().get_config(store_id)
        except NotFound:
            raise HTTPException(404, f"Store {store_id!r} not found")

    # ---------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "contract_version": CONTRACT_VERSION,
            "messenger": app.state.messenger.name,
            "model": settings.agent_model,
            "llm_configured": bool(settings.openrouter_api_key) or llm is not None,
            "stubs": integrations.active_stubs(),
            "demo_key_required": bool(settings.demo_key),
            "warnings": startup_warnings,
        }

    # ---------------------------------------------------------------- stores
    @app.post("/api/stores", response_model=StoreConfig)
    def create_store(req: CreateStoreRequest) -> StoreConfig:
        cfg = templates.build(req.template, req.name, req.jurisdiction)
        return db().create_store(cfg, actor="leader")

    @app.get("/api/stores/{store_id}/config", response_model=StoreConfig)
    def get_config(store_id: str) -> StoreConfig:
        return load(store_id)

    @app.put("/api/stores/{store_id}/config", response_model=StoreConfig)
    def put_config(store_id: str, body: dict = Body(...)) -> StoreConfig:
        load(store_id)
        try:
            return db().mutate(store_id, lambda _d: dict(body), "put_config", {"full_replace": True}, "leader")
        except ConfigInvalid as e:
            raise HTTPException(422, detail=e.errors)

    @app.get("/api/stores/{store_id}/readiness", response_model=Readiness)
    def get_readiness(store_id: str) -> Readiness:
        return readiness.compute(load(store_id))

    # ---------------------------------------------------------------- solve / validate
    @app.post("/api/stores/{store_id}/solve")
    def solve(store_id: str, req: SolveRequest = Body(default_factory=SolveRequest)) -> dict:
        cfg = with_law(load(store_id))
        sched = integrations.solve_week(cfg, time_limit_s=req.time_limit_s or 20)
        try:
            val = integrations.validate(cfg, sched)
        except integrations.StubUnavailable as e:
            raise HTTPException(503, str(e))
        db().save_schedule(store_id, sched, val)
        return {"schedule": sched.model_dump(mode="json"), "validation": val.model_dump(mode="json")}

    @app.post("/api/stores/{store_id}/validate", response_model=ValidationReport)
    def validate(store_id: str, schedule: Schedule) -> ValidationReport:
        cfg = with_law(load(store_id))
        try:
            return integrations.validate(cfg, schedule)
        except integrations.StubUnavailable as e:
            raise HTTPException(503, str(e))

    @app.get("/api/stores/{store_id}/schedule")
    def latest_schedule(store_id: str) -> dict:
        load(store_id)
        try:
            sched, val = db().latest_schedule(store_id)
        except NotFound:
            raise HTTPException(404, "No schedule yet; POST /solve first.")
        return {"schedule": sched.model_dump(mode="json"), "validation": val.model_dump(mode="json") if val else None}

    @app.post("/api/stores/{store_id}/gaps/explain")
    def gaps_explain(store_id: str, body: dict = Body(...)) -> dict:
        cfg = load(store_id)
        try:
            gap = Gap.model_validate(body.get("gap"))
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False))
        try:
            sched, _ = db().latest_schedule(store_id)
        except NotFound:
            sched = None
        reasons = integrations.explain_gap(cfg, sched, gap) if sched is not None else list(gap.reasons)
        return {"text": phrase_gap(cfg, gap, reasons), "reasons": [r.model_dump(mode="json") for r in reasons]}

    # ---------------------------------------------------------------- CSV import
    @app.post("/api/stores/{store_id}/import/{kind}", response_model=ImportPreview)
    async def import_preview(store_id: str, kind: ImportKind, file: UploadFile = File(...)) -> ImportPreview:
        load(store_id)
        data = await file.read()
        pv, rows = await imports.preview(kind, data, app.state.helper_llm)
        db().put(store_id, "import_rows", kind, rows)
        return pv

    @app.post("/api/stores/{store_id}/import/{kind}/commit", response_model=StoreConfig)
    def import_commit(store_id: str, kind: ImportKind, body: dict = Body(...)) -> StoreConfig:
        load(store_id)
        mapping = body.get("mapping") or {}
        cached = db().get(store_id, "import_rows", kind) or []
        rows = body.get("rows") or []
        if not rows or (cached and len(rows) < len(cached)):  # client sent only the preview: use the full parse
            rows = cached
        if not rows:
            raise HTTPException(400, "No rows to import; upload the CSV first.")
        missing = imports.unmapped_required(kind, mapping)
        if missing:
            raise HTTPException(422, f"Required fields not mapped: {missing}")
        warnings: list[str] = []
        extra: dict = {}

        def fn(d):
            extra["out"] = imports.apply_rows(kind, d, mapping, rows, warnings)
        try:
            cfg = db().mutate(store_id, fn, f"import:{kind}", {"rows": len(rows), "mapping": mapping}, "leader")
        except ConfigInvalid as e:
            raise HTTPException(422, detail=e.errors)
        if kind == "history" and extra.get("out") is not None:
            db().put(store_id, "history", "rows", extra["out"])
        db().put(store_id, "import_warnings", kind, warnings)
        return cfg

    # ---------------------------------------------------------------- fix + outreach
    @app.post("/api/stores/{store_id}/fix")
    async def fix(store_id: str, body: dict = Body(...)) -> FixPlan:
        cfg = with_law(load(store_id))
        try:
            sched, _ = db().latest_schedule(store_id)
        except NotFound:
            raise HTTPException(409, "No schedule yet; POST /solve first.")
        try:
            callouts = [CallOut.model_validate(c) for c in body.get("callouts", [])]
            req = FixRequest(config=cfg, schedule=sched, callouts=callouts, day=int(body["day"]), now=int(body["now"]))
        except (ValidationError, KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, str(e))
        try:
            plan = await asyncio.to_thread(integrations.fix_day, req)
        except integrations.StubUnavailable as e:
            raise HTTPException(503, str(e))
        return app.state.outreach.save_plan(store_id, plan, callouts, req.day, req.now, sched)

    @app.post("/api/stores/{store_id}/outreach/start", response_model=OutreachState)
    async def outreach_start(store_id: str, body: dict = Body(...)) -> OutreachState:
        load(store_id)
        try:
            return await app.state.outreach.start(store_id, body.get("plan_id", ""))
        except KeyError:
            raise HTTPException(404, f"No fix plan {body.get('plan_id')!r}")
        except OutreachBusy as e:
            raise HTTPException(409, str(e))

    @app.post("/api/stores/{store_id}/outreach/cancel", response_model=OutreachState)
    async def outreach_cancel(store_id: str) -> OutreachState:
        load(store_id)
        return await app.state.outreach.cancel(store_id)

    @app.get("/api/stores/{store_id}/outreach", response_model=OutreachState)
    def outreach_get(store_id: str) -> OutreachState:
        load(store_id)
        return app.state.outreach.state(store_id)

    @app.get("/api/stores/{store_id}/outreach/stream")
    async def outreach_stream(store_id: str, request: Request) -> StreamingResponse:
        """SSE: `event: state` with an OutreachState snapshot now and on every change; ends after a
        snapshot whose status is not "texting". `: ping` comment every 15 s while waiting."""
        load(store_id)
        mgr = app.state.outreach

        async def stream():
            last = None
            while True:
                ev = mgr.change_event(store_id)
                st = mgr.state(store_id)
                body = st.model_dump_json()
                if body != last:
                    last = body
                    yield f"event: state\ndata: {body}\n\n"
                if st.status != "texting":
                    return
                try:
                    await asyncio.wait_for(ev.wait(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": ping\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/sms/inbound")
    async def sms_inbound(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        if app.state.messenger.name == "twilio":
            base = settings.public_base_url.rstrip("/")
            url = f"{base}{request.url.path}" if base else str(request.url)
            if not twilio_signature_valid(settings.twilio_auth_token, url, form,
                                          request.headers.get("X-Twilio-Signature", "")):
                raise HTTPException(403, "Invalid Twilio signature")
        await app.state.outreach.inbound(form.get("From", ""), form.get("Body", ""))
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")

    @app.post("/api/sms/mock-reply")
    async def sms_mock_reply(body: dict = Body(...)) -> dict:
        if app.state.messenger.name != "mock":
            raise HTTPException(404, "Only available when MESSENGER=mock")
        msg = await app.state.outreach.inbound(str(body.get("from_phone", "")), str(body.get("body", "")))
        return {"ok": True, "interpreted_as": msg.interpreted_as if msg else None}

    # ---------------------------------------------------------------- laws
    @app.get("/api/laws/resolve", response_model=LawPack)
    def laws_resolve(state: str, city: Optional[str] = None) -> LawPack:
        return integrations.resolve_law(Jurisdiction(state=state.upper(), city=city.lower() if city else None))

    # ---------------------------------------------------------------- chat
    @app.post("/api/stores/{store_id}/chat")
    async def chat(store_id: str, req: ChatRequest,
                   auto_cards: Optional[Literal["scripted"]] = Query(None)) -> StreamingResponse:
        load(store_id)
        lock = app.state.turn_locks.setdefault(store_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "A chat turn is already running for this store.")
        waiter = (scripted_waiter(req.card_script) if auto_cards == "scripted"
                  else broker_waiter(app.state.cards, store_id, settings.card_timeout_s))

        async def stream():
            async with lock:
                async for event, data in run_turn(
                    db=db(), llm=app.state.llm, store_id=store_id, mode=req.mode,
                    user_messages=[m.model_dump() for m in req.messages], await_card=waiter,
                ):
                    yield sse(event, data)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/stores/{store_id}/chat/card")
    def chat_card(store_id: str, sub: CardSubmission) -> dict:
        load(store_id)
        if not app.state.cards.submit(store_id, sub.card_id, sub.result):
            raise HTTPException(404, f"No pending card {sub.card_id!r} for this store.")
        return {"ok": True}

    @app.get("/api/stores/{store_id}/audit")
    def audit(store_id: str) -> list[dict]:
        load(store_id)
        return db().audit_log(store_id)

    # ---------------------------------------------------------------- web app
    dist = Path(settings.web_dist) if settings.web_dist else REPO_ROOT / "apps/web/dist"
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            try:
                f = (root / path).resolve()
                f.relative_to(root)  # never serve outside dist (path traversal)
            except (ValueError, OSError):
                return FileResponse(root / "index.html")
            return FileResponse(f if path and f.is_file() else root / "index.html")

    return app


_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """`shiftwright_api.main:app` is created lazily so importing the module has no side effects."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
