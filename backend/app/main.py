"""PropCloser agent API (FastAPI).

Graded endpoints (open, no login):
    POST /chat    {"user_id", "thread_id", "message"} -> {"reply", "tool_calls", "tokens": {"in", "out"}}
    GET  /health  -> ok
Website endpoints:
    GET  /listings                      public catalogue for the customer page
    GET  /admin/stats|leads|visits|followups, POST /admin/followups/{id}   (X-Admin-Token header)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import config
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

        pool = AsyncConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=False,
                                   kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
        await pool.open()
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
    app.state.graph = build_graph(checkpointer=checkpointer, store=store)
    yield
    await repo.close()


app = FastAPI(title="PropCloser API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ── graded API ──

class ChatIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(default="", max_length=8000)


@app.post("/chat")
async def chat(body: ChatIn, request: Request):
    return await run_chat(request.app.state.graph, body.user_id.strip(), body.thread_id.strip(), body.message)


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
async def health():
    return "ok"


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

def require_admin(x_admin_token: str = Header(default="")):
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


class FollowupDecision(BaseModel):
    status: Literal["approved", "rejected"]


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
async def admin_stats():
    return await get_repo().stats()


@app.get("/admin/leads", dependencies=[Depends(require_admin)])
async def admin_leads():
    return await get_repo().admin_leads()


@app.get("/admin/visits", dependencies=[Depends(require_admin)])
async def admin_visits():
    return await get_repo().admin_visits()


@app.get("/admin/followups", dependencies=[Depends(require_admin)])
async def admin_followups():
    return await get_repo().admin_followups()


@app.post("/admin/followups/{followup_id}", dependencies=[Depends(require_admin)])
async def decide_followup(followup_id: int, body: FollowupDecision):
    item = await get_repo().set_followup_status(followup_id, body.status)
    if not item:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return item
