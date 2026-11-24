"""One /chat turn: run the graph for (user_id, thread_id) and shape the graded response.

Response contract (do not change):
    {"reply": str, "tool_calls": [{"name": str, "args": dict}], "tokens": {"in": int, "out": int}}
"""
from __future__ import annotations

import asyncio
import logging
import time
import weakref
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import budget, config
from app.context import Ctx
from app.graph import NOT_EXECUTED
from app.ids import safe_id, thread_key
from app.repo import get_repo

log = logging.getLogger("propcloser")

WELCOME = ("Hi! I'm PropCloser, your property assistant for Islamabad. Are you looking to buy or rent, "
           "and in which area?")
FALLBACK = ("Sorry, I hit a problem answering that. Could you say it again? "
            "You can also tell me the area, budget and type of property you want.")
BUSY = "We're handling a lot of messages right now. Please try again in a few minutes."

# One turn at a time per conversation, and a cap on turns in flight. Entries disappear when nobody uses them.
_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_slots: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_background: set[asyncio.Task] = set()


def _lock(key: str) -> asyncio.Lock:
    full = (id(asyncio.get_running_loop()), key)
    lock = _locks.get(full)
    if lock is None:
        lock = _locks[full] = asyncio.Lock()
    return lock


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(config.MAX_CONCURRENT_TURNS)
    return _slots[loop]


def empty_response(reply: str) -> dict:
    return {"reply": reply, "tool_calls": [], "tokens": {"in": 0, "out": 0}}


def summarize(new_messages: list) -> dict:
    ran = {m.tool_call_id for m in new_messages
           if isinstance(m, ToolMessage) and not m.text.startswith(NOT_EXECUTED)}
    ai = [m for m in new_messages if isinstance(m, AIMessage)]
    tool_calls = [{"name": c["name"], "args": c["args"]} for m in ai for c in (m.tool_calls or []) if c["id"] in ran]
    reply = next((m.text.strip() for m in reversed(ai) if m.text and m.text.strip()), FALLBACK)
    tokens_in = sum((m.usage_metadata or {}).get("input_tokens", 0) for m in ai)
    tokens_out = sum((m.usage_metadata or {}).get("output_tokens", 0) for m in ai)
    return {"reply": reply, "tool_calls": tool_calls, "tokens": {"in": tokens_in, "out": tokens_out}}


async def repair_thread(graph, cfg: dict) -> None:
    """After a failure, close any tool calls left without results so the next Claude call is valid."""
    try:
        messages = (await graph.aget_state(cfg)).values.get("messages", [])
        if not messages:
            return
        answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls), None)
        fixes = [ToolMessage(f"{NOT_EXECUTED}: an error occurred.", tool_call_id=c["id"])
                 for c in (last_ai.tool_calls if last_ai else []) if c["id"] not in answered]
        last = messages[-1]
        if fixes or not (isinstance(last, AIMessage) and not last.tool_calls):
            await graph.aupdate_state(cfg, {"messages": [*fixes, AIMessage(FALLBACK)]}, as_node="update_pipeline")
    except Exception:                                    # repairing must never crash the request
        log.exception("could not repair thread %s", cfg)


async def erase_threads(graph, user_id: str) -> None:
    """After forget_me: delete every stored chat of this lead, or the model would simply read the facts back."""
    prefix = safe_id(user_id) + ":"
    saver = graph.checkpointer
    stored = getattr(saver, "storage", None)             # InMemorySaver; Postgres is asked through the repo
    threads = [t for t in stored if t.startswith(prefix)] if stored is not None else await get_repo().thread_ids(prefix)
    for thread in threads:
        await saver.adelete_thread(thread)


async def _save_spend(usd: float) -> None:
    try:
        await get_repo().add_spend(usd)
    except Exception as exc:
        log.warning("could not store spend: %s", exc)


def _account(new_messages: list) -> float:
    usd = sum(budget.METER.record(m.usage_metadata) for m in new_messages
              if isinstance(m, AIMessage) and m.usage_metadata)
    if usd:
        task = asyncio.create_task(_save_spend(usd))     # the lead does not wait for bookkeeping
        _background.add(task)
        task.add_done_callback(_background.discard)
    return usd


async def run_chat(graph, user_id: str, thread_id: str, message: str) -> dict:
    message = (message or "").strip()
    if not message:
        return empty_response(WELCOME)
    if not budget.METER.allow():
        log.error("SPEND CAP reached: %s", budget.METER.report())
        return empty_response(BUSY)

    key = thread_key(user_id, thread_id)
    cfg = {"configurable": {"thread_id": key}, "recursion_limit": 30}
    human = HumanMessage(message, id=uuid4().hex)
    started = time.monotonic()
    async with _lock(key):
        try:
            async with _slot():
                # durability="exit": one checkpoint write per turn instead of one per node (each is a database round trip)
                out = await asyncio.wait_for(
                    graph.ainvoke({"messages": [human]}, cfg, context=Ctx(user_id=user_id), durability="exit"),
                    timeout=config.REQUEST_TIMEOUT_S)
            messages = out["messages"]
            new = messages[next(i for i, m in enumerate(messages) if m.id == human.id) + 1:]
            result = summarize(new)
            usd = _account(new)
            if any(c["name"] == "forget_me" for c in result["tool_calls"]):
                await erase_threads(graph, user_id)
            log.info("turn ok ms=%d model_calls=%d in=%d out=%d usd=%.6f tools=%s",
                     (time.monotonic() - started) * 1000, sum(bool(m.usage_metadata) for m in new if isinstance(m, AIMessage)),
                     result["tokens"]["in"], result["tokens"]["out"], usd, [c["name"] for c in result["tool_calls"]])
            return result
        except Exception as exc:                         # friendly to the lead, loud in the logs
            log.exception("CHAT FAILED %s: %s: %s", key, type(exc).__name__, exc)
            await repair_thread(graph, cfg)
            return empty_response(FALLBACK)
