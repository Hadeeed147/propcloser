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
from app.repo import MemoryRepo, set_repo

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
