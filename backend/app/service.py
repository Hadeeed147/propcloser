"""One /chat turn: run the graph for (user_id, thread_id) and shape the graded response.

Response contract (do not change):
    {"reply": str, "tool_calls": [{"name": str, "args": dict}], "tokens": {"in": int, "out": int}}
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import config
from app.context import Ctx
from app.graph import NOT_EXECUTED

log = logging.getLogger("propcloser")

WELCOME = ("Hi! I'm PropCloser, your property assistant for Islamabad. Are you looking to buy or rent, "
           "and in which area?")
FALLBACK = ("Sorry, I hit a problem answering that. Could you say it again? "
            "You can also tell me the area, budget and type of property you want.")

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)   # one turn at a time per conversation


def thread_key(user_id: str, thread_id: str) -> str:
    """Checkpointer key. Includes user_id so two users sending the same thread_id never share a chat."""
    return f"{user_id}:{thread_id}"


def empty_response(reply: str) -> dict:
    return {"reply": reply, "tool_calls": [], "tokens": {"in": 0, "out": 0}}


def summarize(new_messages: list) -> dict:
    ran = {m.tool_call_id for m in new_messages
           if isinstance(m, ToolMessage) and not m.text.startswith(NOT_EXECUTED)}
    tool_calls = [{"name": c["name"], "args": c["args"]}
                  for m in new_messages if isinstance(m, AIMessage)
                  for c in (m.tool_calls or []) if c["id"] in ran]
    ai = [m for m in new_messages if isinstance(m, AIMessage)]
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


async def run_chat(graph, user_id: str, thread_id: str, message: str) -> dict:
    message = (message or "").strip()
    if not message:
        return empty_response(WELCOME)
    cfg = {"configurable": {"thread_id": thread_key(user_id, thread_id)}, "recursion_limit": 25}
    async with _locks[cfg["configurable"]["thread_id"]]:
        before = len((await graph.aget_state(cfg)).values.get("messages", []))
        try:
            out = await asyncio.wait_for(
                graph.ainvoke({"messages": [HumanMessage(message)]}, cfg, context=Ctx(user_id=user_id)),
                timeout=config.REQUEST_TIMEOUT_S)
            return summarize(out["messages"][before:])
        except Exception as exc:                         # friendly to the lead, loud in the logs
            log.exception("CHAT FAILED %s: %s: %s", cfg["configurable"]["thread_id"], type(exc).__name__, exc)
            await repair_thread(graph, cfg)
            return empty_response(FALLBACK)
