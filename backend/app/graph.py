r"""The PropCloser LangGraph.

START -> guard -(blocked)-> refuse -> END
              \-> load_profile -(exact "yes" to a waiting action)-> confirm_fast -> tools
                              \-> closer -(safe tools)-> tools -> load_profile -> closer ...
                                         -(risky tool)-> approval_gate -(already said yes)-> tools
                                                                       -(not yet: asks)-> update_pipeline
                                         -(no tools)-> update_pipeline -> END
A confirm_fast action ends in say_done (a fixed reply in the lead's language): the whole turn costs 0 tokens.

Only `closer` calls the model, at most MAX_MODEL_CALLS times per turn. Everything else is plain code.
"""
from __future__ import annotations

import logging
import re
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command

from app import config
from app.approval import is_exact_yes, is_yes
from app.context import Ctx
from app.guard import check_message, refusal_for
from app.prompts import request_messages
from app.replies import reply_for
from app.repo import get_repo, lead_status
from app.tools import RISKY_TOOLS, TOOL_SPECS, TOOLS, full_memory, pick_visit, tool_error, visit_label

log = logging.getLogger("propcloser")
NOT_EXECUTED = "Not executed"
EMPTY_REPLY = ("I can help you buy or rent property in Islamabad. "
               "Could you tell me the area, your budget and what kind of place you want?")


def keep_last(old, new):
    """Reducer: when two tools in the same step write this key, the last write wins (LangGraph's default is to crash)."""
    return new


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]          # short-term memory (checkpointer)
    lead_profile: dict                                           # long-term memory, reloaded after every tool step
    pending_action: Annotated[dict | None, keep_last]            # a risky action waiting for the lead's yes
    blocked_reason: str | None                                   # set by guard


def human_turns(messages: list[AnyMessage]) -> int:
    return sum(isinstance(m, HumanMessage) for m in messages)


def without_blocked(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Drop refused attacks and our refusal, so the attack text never reaches the model on a later turn."""
    out: list[AnyMessage] = []
    for m in messages:
        if isinstance(m, AIMessage) and m.additional_kwargs.get("blocked"):
            if out and isinstance(out[-1], HumanMessage):
                out.pop()
            continue
        out.append(m)
    return out


def window(messages: list[AnyMessage], n: int) -> list[AnyMessage]:
    """Last ~n messages, always starting at a user message so tool calls are never split."""
    if len(messages) <= n:
        return messages
    start = len(messages) - n
    while start > 0 and not isinstance(messages[start], HumanMessage):
        start -= 1
    return messages[start:]


def model_calls_this_turn(messages: list[AnyMessage]) -> int:
    count = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        count += isinstance(m, AIMessage)
    return count


def last_human_text(messages: list[AnyMessage]) -> str:
    return next((m.text for m in reversed(messages) if isinstance(m, HumanMessage)), "")


ASKED_ABOUT = {"cancel_visit": r"cancel", "forget_me": r"delete|forget|erase|remove"}


def model_already_asked(messages: list[AnyMessage], tool: str) -> bool:
    """The agent itself just asked "shall I cancel it?" and the lead answered exactly yes: do not ask a second time."""
    i = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), 0)
    asked = messages[i - 1].text if i and isinstance(messages[i - 1], AIMessage) else ""
    return (tool in ASKED_ABOUT and "?" in asked and bool(re.search(ASKED_ABOUT[tool], asked, re.I))
            and is_exact_yes(messages[i].text))


def waiting_since_earlier(state: State) -> dict | None:
    """The pending action, but only if it was created by an EARLIER user message (you cannot pre-approve)."""
    pending = state.get("pending_action")
    return pending if pending and human_turns(state["messages"]) > pending["human_turn"] else None


def make_model() -> ChatAnthropic:
    """claude-haiku-5-5 settings that matter:
    - no temperature/top_p: this model rejects any non-default value with a 400
    - thinking off: it is ON by default, is billed as output, and its blocks become invalid when the
      system prompt changes between turns (ours does: it carries the lead's memory)
    """
    return ChatAnthropic(model=config.MODEL, max_tokens=config.MAX_TOKENS, thinking={"type": "disabled"},
                         effort=config.EFFORT, timeout=config.MODEL_TIMEOUT_S, max_retries=config.MODEL_RETRIES)


def build_graph(llm: BaseChatModel | None = None, checkpointer=None, store=None):
    base = llm or make_model()
    model = base.bind_tools(TOOL_SPECS)
    final_model = base.bind_tools(TOOL_SPECS, tool_choice={"type": "none"})      # last allowed call: must answer in words

    # ── nodes ──

    def guard(state: State) -> dict:
        return {"blocked_reason": check_message(state["messages"][-1].text)}

    def refuse(state: State) -> dict:
        return {"messages": [AIMessage(refusal_for(state.get("blocked_reason")), additional_kwargs={"blocked": True})]}

    async def load_profile(state: State, runtime: Runtime[Ctx]) -> dict:
        return {"lead_profile": await full_memory(runtime.store, runtime.context.user_id)}

    def confirm_fast(state: State) -> dict:
        """The lead said exactly "yes": write the approved tool call ourselves and skip the model.
        (The instructor's urgent_reading_guard does the same, so the model can never forget to act.)"""
        pending = state["pending_action"]
        call = {"name": pending["tool"], "args": pending["args"], "id": f"yes_{uuid4().hex[:10]}", "type": "tool_call"}
        return {"messages": [AIMessage(content="", tool_calls=[call])]}

    async def closer(state: State) -> dict:
        history = window(without_blocked(state["messages"]), config.HISTORY_MESSAGES)
        last_call = model_calls_this_turn(state["messages"]) >= config.MAX_MODEL_CALLS - 1
        reply = await (final_model if last_call else model).ainvoke(
            request_messages(history, state.get("lead_profile") or {}, state.get("pending_action")))
        stop = reply.response_metadata.get("stop_reason")
        if stop == "max_tokens" and reply.tool_calls:            # a cut-off tool call may have wrong arguments
            log.warning("reply cut off at max_tokens inside a tool call")
        unusable = reply.tool_calls and (last_call or stop == "max_tokens")
        if unusable or (not reply.tool_calls and not reply.text.strip()):     # never an empty bubble
            log.warning("replacing unusable model reply, stop_reason=%s last_call=%s", stop, last_call)
            reply = AIMessage(reply.text.strip() or EMPTY_REPLY, id=reply.id, usage_metadata=reply.usage_metadata)
        return {"messages": [reply]}

    def say_done(state: State) -> dict:
        """The lead confirmed and the action ran: answer from a template, no model call."""
        artifact = getattr(state["messages"][-1], "artifact", None) or {"reply": "gone", "what": ""}
        recent = [m.text for m in state["messages"] if isinstance(m, HumanMessage)][-4:]
        return {"messages": [AIMessage(reply_for(artifact["reply"], artifact["what"], recent))]}

    async def approval_gate(state: State, runtime: Runtime[Ctx]) -> Command[Literal["tools", "update_pipeline"]]:
        """Human-in-the-loop without interrupt(): a risky call runs only after the lead's yes in a later message."""
        messages = state["messages"]
        last = messages[-1]
        pending = waiting_since_earlier(state)

        def approved(call) -> bool:
            if model_already_asked(messages, call["name"]):
                return True
            same = pending and pending["tool"] == call["name"] and (
                pending["args"] == call["args"] or not any(call["args"].values()))
            return bool(same and is_yes(last_human_text(messages), call["name"]))

        risky = [c for c in last.tool_calls if c["name"] in RISKY_TOOLS]
        if all(approved(c) for c in risky):
            return Command(goto="tools")

        safe = [c for c in last.tool_calls if c["name"] not in RISKY_TOOLS]
        if safe:
            # Run the safe calls now; drop the risky ones (same message id => replaced in the history).
            safe_ids = {c["id"] for c in safe}
            content = last.content
            if isinstance(content, list):
                content = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_use"
                                                      and b.get("id") not in safe_ids)]
            return Command(goto="tools", update={"messages": [AIMessage(
                content=content, tool_calls=safe, id=last.id, usage_metadata=last.usage_metadata,
                response_metadata=last.response_metadata)]})

        call = risky[0]
        waiting = state.get("pending_action")
        update: dict = {}
        if call["name"] == "confirm_visit":
            if waiting and waiting["tool"] == "confirm_visit":       # asking again now: the next message may answer it
                update["pending_action"] = {**waiting, "human_turn": human_turns(messages)}
            ask = (f"Just to confirm: shall I {waiting['summary']}? Reply \"yes\" (haan) to confirm."
                   if waiting and waiting["tool"] == "confirm_visit"
                   else "Which property and time would you like to visit? I'll check the free slots first.")
        else:
            if call["name"] == "cancel_visit":
                visit, _ = await pick_visit(runtime.context.user_id, call["args"].get("visit_id"), ("pending", "confirmed"))
                if not visit:
                    return Command(goto="tools")                 # harmless: the tool says which visits exist
                summary, args = f"cancel your visit to {visit_label(visit)}", {"visit_id": visit["id"]}
            else:
                summary, args = "delete everything I remember about you", {}
            update["pending_action"] = {"tool": call["name"], "args": args, "summary": summary,
                                        "human_turn": human_turns(messages)}
            ask = f"Just to confirm: shall I {summary}? Reply \"yes\" (haan) to confirm."
        skipped = [ToolMessage(f"{NOT_EXECUTED}: waiting for the lead to confirm.", tool_call_id=c["id"])
                   for c in last.tool_calls]
        return Command(goto="update_pipeline", update={**update, "messages": [*skipped, AIMessage(ask)]})

    async def update_pipeline(state: State, runtime: Runtime[Ctx]) -> dict:
        repo = get_repo()
        user_id = runtime.context.user_id
        await repo.set_status(user_id, lead_status(state.get("lead_profile") or {},
                                                   await repo.user_visits(user_id)))
        return {}

    # ── routing ──

    def route_after_guard(state: State) -> Literal["refuse", "load_profile"]:
        return "refuse" if state.get("blocked_reason") else "load_profile"

    def route_after_load(state: State) -> Literal["confirm_fast", "say_done", "closer"]:
        last = state["messages"][-1]
        if isinstance(last, ToolMessage) and last.tool_call_id.startswith("yes_"):
            return "say_done"
        pending = waiting_since_earlier(state)
        # Only the message right after the question: a later "yes" may be answering something else.
        answers_it = pending and human_turns(state["messages"]) == pending["human_turn"] + 1
        if isinstance(last, HumanMessage) and answers_it and is_exact_yes(last.text):
            return "confirm_fast"
        return "closer"

    def route_after_closer(state: State) -> Literal["tools", "approval_gate", "update_pipeline"]:
        calls = getattr(state["messages"][-1], "tool_calls", None)
        if not calls:
            return "update_pipeline"
        return "approval_gate" if any(c["name"] in RISKY_TOOLS for c in calls) else "tools"

    g = StateGraph(State, context_schema=Ctx)
    g.add_node("guard", guard)
    g.add_node("refuse", refuse)
    g.add_node("load_profile", load_profile)
    g.add_node("confirm_fast", confirm_fast)
    g.add_node("closer", closer)
    g.add_node("say_done", say_done)
    g.add_node("tools", ToolNode(TOOLS, handle_tool_errors=tool_error))
    g.add_node("approval_gate", approval_gate)
    g.add_node("update_pipeline", update_pipeline)

    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", route_after_guard, ["refuse", "load_profile"])
    g.add_edge("refuse", END)
    g.add_conditional_edges("load_profile", route_after_load, ["confirm_fast", "say_done", "closer"])
    g.add_edge("confirm_fast", "tools")
    g.add_edge("say_done", "update_pipeline")
    g.add_conditional_edges("closer", route_after_closer, ["tools", "approval_gate", "update_pipeline"])
    g.add_edge("tools", "load_profile")
    g.add_edge("update_pipeline", END)
    return g.compile(checkpointer=checkpointer, store=store)
