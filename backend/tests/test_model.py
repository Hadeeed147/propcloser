"""What we actually send to claude-haiku-5-5, checked without a key."""
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage

from app.prompts import request_messages
from app.service import FALLBACK
from conftest import payload
from test_graph import chat


def _req(profile=None, pending=None):
    return payload(request_messages([HumanMessage("hi")], profile or {}, pending))


def test_no_sampling_parameters_anywhere():
    assert "temperature" not in json.dumps({k: v for k, v in _req().items() if k not in ("messages", "system", "tools")})


def test_thinking_off_effort_low_and_room_to_answer():
    r = _req()
    assert r["model"] == "claude-haiku-5-5"
    assert r["thinking"] == {"type": "disabled"} and r["output_config"] == {"effort": "low"} and r["max_tokens"] == 700


def test_system_is_cached_and_never_changes_memory_comes_last():
    a, b = _req({"area": "G-13"}), _req({"area": "B-17"}, {"summary": "a visit"})
    assert a["system"] == b["system"] and a["system"][0]["cache_control"] == {"type": "ephemeral"}
    last_a, last_b = a["messages"][-1], b["messages"][-1]
    assert last_a["role"] == last_b["role"] == "system"
    assert "G-13" in last_a["content"] and "B-17" in last_b["content"] and "a visit" in last_b["content"]
    assert a["messages"][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "new lead" in _req()["messages"][-1]["content"]


def test_empty_model_reply_becomes_a_useful_answer(make_graph):
    graph, _ = make_graph([AIMessage(content="", response_metadata={"stop_reason": "refusal"})])
    reply = chat(graph, "u", "t", "hello there")["reply"]
    assert reply != FALLBACK and "property" in reply.lower()


def test_a_tool_call_cut_off_by_max_tokens_is_not_run(make_graph, repo):
    cut = AIMessage(content="", tool_calls=[{"name": "request_visit", "args": {"listing_id": 2}, "id": "c", "type": "tool_call"}],
                    response_metadata={"stop_reason": "max_tokens"})
    graph, _ = make_graph([cut])
    out = chat(graph, "cut", "t", "book it")
    assert out["tool_calls"] == [] and repo.visits == [] and out["reply"] != FALLBACK


def test_model_failure_is_logged_with_its_cause(make_graph, caplog):
    graph, _ = make_graph([])                      # the scripted model raises on its first call
    with caplog.at_level(logging.ERROR):
        assert chat(graph, "u", "t", "house in G-13")["reply"] == FALLBACK
    assert "AssertionError" in caplog.text and "model called more times" in caplog.text


def test_benchmark_never_passes_a_fallback_reply():
    from app.service import BUSY
    from run_bench import check
    for reply in (FALLBACK, BUSY):
        ok, why = check({"check": {"reply_none": ["Sana"]}}, [{"reply": reply, "tool_calls": []}])
        assert not ok and "fallback" in why
