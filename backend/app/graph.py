r"""The PropCloser LangGraph.

START -> guard -(blocked)-> refuse -> END
             \-> load_profile -> closer -(safe tools)-> tools -> closer
                                       -(risky tool)-> approval_gate -(lead said yes)-> tools
                                                                     -(not yet)-> update_pipeline
                                       -(no tools)-> update_pipeline -> END

Only `closer` calls the model. Everything else is plain code, so most turns cost one Haiku call.
"""
from __future__ import annotations

import logging
import re
from typing import Annotated, Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command

from app import config
from app.context import Ctx
from app.guard import check_message, refusal_for
from app.prompts import system_message
from app.repo import get_repo, lead_status
from app.tools import RISKY_TOOLS, TOOLS, read_profile

log = logging.getLogger("propcloser")
NOT_EXECUTED = "Not executed"
EMPTY_REPLY = ("I can help you buy or rent property in Islamabad. "
               "Could you tell me the area, your budget and what kind of place you want?")
YES = re.compile(r"\b(yes|yeah|yep|yup|confirm(ed)?|ok(ay)?|sure|book it|go ahead|done|haan|han|ji|jee|"
                 r"theek hai|thik hai|kar do|kardo)\b", re.I)
NO = re.compile(r"^\s*(no|nope)\b|\b(not now|cancel|don'?t book|nahi|nahin)\b", re.I)


def human_turns(messages: list[AnyMessage]) -> int:
    return sum(isinstance(m, HumanMessage) for m in messages)


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]   # short-term memory (checkpointer)
    lead_profile: dict                                   # long-term memory, loaded each turn
    pending_action: dict | None                          # a held visit waiting for the lead's yes
    blocked_reason: str | None                           # set by guard


def window(messages: list[AnyMessage], n: int) -> list[AnyMessage]:
    """Last ~n messages, always starting at a user message so tool calls are never split."""
    if len(messages) <= n:
        return messages
    start = len(messages) - n
    while start > 0 and not isinstance(messages[start], HumanMessage):
        start -= 1
    return messages[start:]


def last_human_text(messages: list[AnyMessage]) -> str:
    return next((m.text for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def make_model() -> ChatAnthropic:
    """claude-haiku-5-5 settings that matter:
    - no temperature/top_p: this model rejects any non-default value with a 400
    - thinking off: it is ON by default, is billed as output, and its blocks become invalid when the
      system prompt changes between turns (ours does: it carries the lead's memory)
    """
    return ChatAnthropic(model=config.MODEL, max_tokens=config.MAX_TOKENS, thinking={"type": "disabled"},
                         effort=config.EFFORT, timeout=20, max_retries=2)


def build_graph(llm: BaseChatModel | None = None, checkpointer=None, store=None):
    model = (llm or make_model()).bind_tools(TOOLS)

    # ── nodes ──

    def guard(state: State) -> dict:
        return {"blocked_reason": check_message(state["messages"][-1].text)}

    def refuse(state: State) -> dict:
        return {"messages": [AIMessage(refusal_for(state.get("blocked_reason")))]}

    async def load_profile(state: State, runtime: Runtime[Ctx]) -> dict:
        return {"lead_profile": await read_profile(runtime.store, runtime.context.user_id)}

    async def closer(state: State) -> dict:
        system = system_message(state.get("lead_profile") or {}, state.get("pending_action"))
        reply = await model.ainvoke([system, *window(state["messages"], config.HISTORY_MESSAGES)])
        if not reply.tool_calls and not reply.text.strip():      # refused or cut off: never send an empty bubble
            log.warning("empty model reply, stop_reason=%s", reply.response_metadata.get("stop_reason"))
            reply = AIMessage(EMPTY_REPLY, id=reply.id, usage_metadata=reply.usage_metadata)
        return {"messages": [reply]}

    def approval_gate(state: State) -> Command[Literal["tools", "update_pipeline"]]:
        """Human-in-the-loop without interrupt(): risky calls run only after the lead's explicit yes,
        given in a LATER message than the one that created the pending visit."""
        messages = state["messages"]
        last = messages[-1]
        said = last_human_text(messages)
        pending = state.get("pending_action")
        if (pending and human_turns(messages) > pending.get("human_turn", 0)
                and YES.search(said) and not NO.search(said)):
            return Command(goto="tools")

        safe = [c for c in last.tool_calls if c["name"] not in RISKY_TOOLS]
        if safe:
            # Drop only the risky calls (same message id => replaced in history) and run the safe ones.
            safe_ids = {c["id"] for c in safe}
            content = last.content
            if isinstance(content, list):
                content = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_use"
                                                      and b.get("id") not in safe_ids)]
            trimmed = AIMessage(content=content, tool_calls=safe, id=last.id,
                                usage_metadata=last.usage_metadata, response_metadata=last.response_metadata)
            return Command(goto="tools", update={"messages": [trimmed]})

        skipped = [ToolMessage(f"{NOT_EXECUTED}: waiting for the lead to confirm.", tool_call_id=c["id"])
                   for c in last.tool_calls]
        ask = (f"Just to confirm: shall I book {pending['summary']}? Reply \"yes\" to confirm." if pending
               else "Which property and time would you like to visit? I'll check the free slots first.")
        return Command(goto="update_pipeline", update={"messages": [*skipped, AIMessage(ask)]})

    async def update_pipeline(state: State, runtime: Runtime[Ctx]) -> dict:
        repo = get_repo()
        user_id = runtime.context.user_id
        await repo.set_status(user_id, lead_status(state.get("lead_profile") or {},
                                                   await repo.user_visits(user_id)))
        return {}

    # ── routing ──

    def route_after_guard(state: State) -> Literal["refuse", "load_profile"]:
        return "refuse" if state.get("blocked_reason") else "load_profile"

    def route_after_closer(state: State) -> Literal["tools", "approval_gate", "update_pipeline"]:
        calls = getattr(state["messages"][-1], "tool_calls", None)
        if not calls:
            return "update_pipeline"
        return "approval_gate" if any(c["name"] in RISKY_TOOLS for c in calls) else "tools"

    g = StateGraph(State, context_schema=Ctx)
    g.add_node("guard", guard)
    g.add_node("refuse", refuse)
    g.add_node("load_profile", load_profile)
    g.add_node("closer", closer)
    g.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    g.add_node("approval_gate", approval_gate)
    g.add_node("update_pipeline", update_pipeline)

    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", route_after_guard, ["refuse", "load_profile"])
    g.add_edge("refuse", END)
    g.add_edge("load_profile", "closer")
    g.add_conditional_edges("closer", route_after_closer, ["tools", "approval_gate", "update_pipeline"])
    g.add_edge("tools", "closer")
    g.add_edge("update_pipeline", END)
    return g.compile(checkpointer=checkpointer, store=store)
