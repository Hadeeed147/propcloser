"""What we actually send to claude-haiku-5-5, checked without a key."""
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage

from app.prompts import system_message
from app.service import FALLBACK
from conftest import payload
from test_graph import chat


def _req(profile=None, pending=None):
    return payload([system_message(profile or {}, pending), HumanMessage("hi")])


def test_no_sampling_parameters_anywhere():
    assert "temperature" not in json.dumps({k: v for k, v in _req().items() if k not in ("messages", "system", "tools")})


def test_thinking_off_effort_low_and_room_to_answer():
    r = _req()
    assert r["model"] == "claude-haiku-5-5"
    assert r["thinking"] == {"type": "disabled"} and r["output_config"] == {"effort": "low"} and r["max_tokens"] == 700


def test_static_prompt_is_cached_and_never_changes():
    a, b = _req({"area": "G-13"}), _req({"area": "B-17"}, {"summary": "a visit"})
    assert a["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert a["system"][0] == b["system"][0]
    assert "G-13" in a["system"][1]["text"] and "B-17" in b["system"][1]["text"] and "a visit" in b["system"][1]["text"]
    assert "new lead" in _req()["system"][1]["text"]


def test_empty_model_reply_becomes_a_useful_answer(make_graph):
    graph, _ = make_graph([AIMessage(content="", response_metadata={"stop_reason": "refusal"})])
    reply = chat(graph, "u", "t", "hello there")["reply"]
    assert reply != FALLBACK and "property" in reply.lower()


def test_model_failure_is_logged_with_its_cause(make_graph, caplog):
    graph, _ = make_graph([])                      # the scripted model raises on its first call
    with caplog.at_level(logging.ERROR):
        assert chat(graph, "u", "t", "house in G-13")["reply"] == FALLBACK
    assert "AssertionError" in caplog.text and "model called more times" in caplog.text


def test_benchmark_never_passes_a_fallback_reply():
    from run_bench import check
    ok, why = check({"check": {"reply_none": ["Sana"]}}, [{"reply": FALLBACK, "tool_calls": []}])
    assert not ok and "fallback" in why
