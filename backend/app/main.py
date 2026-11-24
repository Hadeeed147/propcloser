"""PropCloser agent API (FastAPI).

Graded endpoints (open, no login):
    POST /chat    {"user_id", "thread_id", "message"} -> {"reply", "tool_calls", "tokens": {"in", "out"}}
    GET  /health  -> ok
Website endpoints:
    GET  /listings                      public catalogue for the customer page
    GET  /admin/stats|leads|visits|followups, POST /admin/followups/{id}   (X-Admin-Token header)
"""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, BeforeValidator, Field

from app import budget, config
from app.followups import sweep
from app.graph import build_graph
from app.repo import MemoryRepo, PostgresRepo, get_repo, search, set_repo
from app.service import run_chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("propcloser")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.DATABASE_URL:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        # check= replaces connections Neon closed while it was asleep (it suspends after a few idle minutes)
        pool = AsyncConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=False, timeout=15, max_idle=120,
                                   max_lifetime=1800, check=AsyncConnectionPool.check_connection,
                                   kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row,
                                           "connect_timeout": 10, "keepalives": 1, "keepalives_idle": 30})
        await pool.open(wait=True, timeout=60)
        checkpointer, store, repo = AsyncPostgresSaver(pool), AsyncPostgresStore(pool), PostgresRepo(pool)
        await checkpointer.setup()
        await store.setup()
        log.info("Using Neon Postgres for checkpoints, long-term memory and data")
    else:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        checkpointer, store, repo = InMemorySaver(), InMemoryStore(), MemoryRepo()
        log.warning("DATABASE_URL not set: IN-MEMORY mode. Fine for local dev, NOT for deployment "
                    "(memory is lost on restart).")
    await repo.setup()
    set_repo(repo)
    budget.METER.total = max(budget.METER.total, await repo.spent_usd())
    if config.DATABASE_URL and not admin_token_ok():
        log.error("ADMIN_TOKEN is missing or weak: the admin API stays closed until it is set (12+ characters)")
    app.state.graph = build_graph(checkpointer=checkpointer, store=store)
    yield
    await repo.close()


app = FastAPI(title="PropCloser API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ── graded API ──

def _text(value) -> str:
    """Clients send numbers, nulls and stray NUL bytes (which Postgres rejects). Accept them all as text."""
    return "" if value is None else str(value).replace("\x00", "").strip()


Text = Annotated[str, BeforeValidator(_text)]


class ChatIn(BaseModel):
    user_id: Text = Field(min_length=1, max_length=256)
    thread_id: Text = Field(default="default", max_length=256)
    message: Text = ""


@app.post("/chat")
async def chat(body: ChatIn, request: Request):
    return await run_chat(request.app.state.graph, body.user_id, body.thread_id or "default", body.message)


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
async def health():
    return "ok"


@app.get("/ready")
async def ready():
    """Deeper check than /health: can we really serve? Costs no tokens. Used by the keep-alive ping."""
    try:
        database = await get_repo().ping()
    except Exception as exc:
        log.error("READY: database check failed: %s", exc)
        database = False
    problems = [p for p, bad in {"database unreachable": not database,
                                 "in-memory storage (set DATABASE_URL)": get_repo().kind != "postgres",
                                 "ANTHROPIC_API_KEY missing": not os.getenv("ANTHROPIC_API_KEY"),
                                 "spend cap reached": not budget.METER.allow()}.items() if bad]
    return JSONResponse(status_code=503 if problems else 200,
                        content={"ready": not problems, "storage": get_repo().kind, "problems": problems})


@app.exception_handler(RequestValidationError)
async def bad_request(request: Request, exc: RequestValidationError):
    # Same response shape as /chat, so a malformed request never breaks the caller.
    return JSONResponse(status_code=422, content={
        "reply": "Please send JSON with user_id, thread_id and message.", "tool_calls": [],
        "tokens": {"in": 0, "out": 0}, "error": exc.errors()[:3]}, )


@app.exception_handler(Exception)
async def crashed(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=200 if request.url.path == "/chat" else 500, content={
        "reply": "Sorry, something went wrong. Please try again.", "tool_calls": [], "tokens": {"in": 0, "out": 0}})


@app.get("/")
async def root():
    return {"name": "PropCloser API", "track": "DealCloser", "docs": "/docs", "health": "/health",
            "storage": get_repo().kind}


# ── customer website ──

@app.get("/listings")
async def listings(purpose: Literal["sale", "rent"] = "sale", area: Optional[str] = None,
                   property_type: Optional[Literal["house", "flat", "plot"]] = None,
                   min_beds: Optional[int] = None, max_price_pkr: Optional[int] = None):
    rows, exact = search(await get_repo().all_listings(), purpose, area, property_type, min_beds, max_price_pkr,
                         limit=60)
    return {"exact": exact, "listings": rows}


# ── admin dashboard ──

def admin_token_ok() -> bool:
    return len(config.ADMIN_TOKEN) >= 12 and config.ADMIN_TOKEN != "change-me"


def require_admin(x_admin_token: str = Header(default="")):
    if config.DATABASE_URL and not admin_token_ok():      # deployed with a default token: closed, not open
        raise HTTPException(status_code=503, detail="Set ADMIN_TOKEN (12+ characters) on the server")
    if not hmac.compare_digest(x_admin_token.encode(), config.ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin token")


class FollowupDecision(BaseModel):
    status: Literal["approved", "rejected"]


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
async def admin_stats():
    return await get_repo().stats()


@app.get("/admin/usage", dependencies=[Depends(require_admin)])
async def admin_usage():
    return budget.METER.report()


@app.get("/admin/leads", dependencies=[Depends(require_admin)])
async def admin_leads():
    return await get_repo().admin_leads()


@app.get("/admin/visits", dependencies=[Depends(require_admin)])
async def admin_visits():
    return await get_repo().admin_visits()


@app.get("/admin/followups", dependencies=[Depends(require_admin)])
async def admin_followups():
    return await get_repo().admin_followups()


@app.post("/admin/sweep", dependencies=[Depends(require_admin)])
async def sweep_quiet_leads(idle_hours: float = 24):
    """Draft follow-ups for leads who went quiet. Drafts wait for approval; nothing is sent."""
    return {"drafted": await sweep(get_repo(), idle_hours)}


@app.post("/admin/followups/{followup_id}", dependencies=[Depends(require_admin)])
async def decide_followup(followup_id: int, body: FollowupDecision):
    item = await get_repo().set_followup_status(followup_id, body.status)
    if not item:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return item
