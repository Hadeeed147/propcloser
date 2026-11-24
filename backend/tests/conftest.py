"""Test helpers: a scripted chat model so the real graph runs without an API key or a database."""
import itertools

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field

from app.graph import build_graph
from app import config
from app.repo import MemoryRepo, set_repo

config.DATABASE_URL = ""          # unit tests never touch a real database, even if .env has one

_ids = itertools.count(1)
USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def say(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata=USAGE)


def call(tool_name: str, /, **args) -> AIMessage:
    return AIMessage(content="", usage_metadata=USAGE,
                     tool_calls=[{"name": tool_name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}])


class ScriptedModel(BaseChatModel):
    """Returns the scripted AI messages in order and records what it was sent."""
    script: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not self.script:
            raise AssertionError("model called more times than scripted")
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


@pytest.fixture(autouse=True)
def fresh_meter(monkeypatch):
    from app import budget
    monkeypatch.setattr(budget, "METER", budget.SpendMeter(total_cap=1.0, hourly_cap=1.0))


@pytest.fixture
def repo():
    r = MemoryRepo()
    set_repo(r)
    return r


@pytest.fixture
def make_graph(repo):
    def _make(script):
        model = ScriptedModel(script=list(script))
        return build_graph(llm=model, checkpointer=InMemorySaver(), store=InMemoryStore()), model
    return _make


def payload(messages):
    """The exact JSON request the REAL Claude client would send (built locally, nothing is sent)."""
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-a-real-key")
    from app.graph import make_model
    from app.tools import TOOL_SPECS
    bound = make_model().bind_tools(TOOL_SPECS)
    return bound.bound._get_request_payload(messages, **bound.kwargs)


def assert_tool_calls_answered(request: dict):
    """Claude rejects a history where a tool_use has no tool_result in the next message."""
    msgs = request["messages"]
    for i, m in enumerate(msgs):
        if m["role"] != "assistant" or isinstance(m["content"], str):
            continue
        asked = {b["id"] for b in m["content"] if b["type"] == "tool_use"}
        if asked:
            nxt = msgs[i + 1]["content"] if i + 1 < len(msgs) else []
            got = {b.get("tool_use_id") for b in nxt if isinstance(b, dict) and b["type"] == "tool_result"}
            assert asked == got, f"orphan tool calls: {asked ^ got}"


def two_calls(*pairs) -> AIMessage:
    """One AI message that calls several tools at once."""
    return AIMessage(content="", usage_metadata=USAGE, tool_calls=[
        {"name": n, "args": a, "id": f"call_{next(_ids)}", "type": "tool_call"} for n, a in pairs])
