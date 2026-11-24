"""Long-term memory: what is saved, what is never saved, show and forget."""
import pytest

from app.guard import check_message
from app.privacy import redact
from conftest import call, say
from test_graph import chat


def test_free_text_notes_survive_into_a_new_thread(make_graph):
    graph, model = make_graph([call("save_lead_profile", note="has two dogs, needs a lawn"), say("Noted."), say("Two dogs.")])
    chat(graph, "mem1", "a", "I have two dogs so I need a lawn")
    chat(graph, "mem1", "b", "what pets do I have?")
    assert "has two dogs, needs a lawn" in model.seen[-1][-1].text


def test_later_facts_override_and_notes_do_not_repeat(make_graph):
    graph, model = make_graph([call("save_lead_profile", budget_pkr=20_000_000, note="wants a corner plot"), say("ok"),
                               call("save_lead_profile", budget_pkr=40_000_000, note="wants a corner plot"), say("ok"), say("4 crore")])
    chat(graph, "mem2", "a", "2 crore")
    chat(graph, "mem2", "a", "make it 4 crore")
    chat(graph, "mem2", "b", "my budget?")
    memory = model.seen[-1][-1].text
    assert "4 crore" in memory and "2 crore" not in memory and memory.count("wants a corner plot") == 1


@pytest.mark.parametrize("secret", ["0300-1234567", "+92 321 7654321", "03211234567", "35202-1234567-1", "3520212345671",
                                    "4111 1111 1111 1111", "ali@example.com"])
def test_private_identifiers_are_redacted(secret):
    assert secret not in redact(f"reach me on {secret} please")


@pytest.mark.parametrize("ok", ["budget 30000000", "3,00,00,000", "5 marla in G-13/4", "visit 2026-11-28T15:00"])
def test_normal_property_text_is_untouched(ok):
    assert redact(ok) == ok


def test_redaction_happens_before_saving(make_graph, repo):
    graph, model = make_graph([call("save_lead_profile", name="Ali", note="call 0300-1234567 after 5pm"), say("ok"), say("ok")])
    chat(graph, "mem3", "a", "call me")
    chat(graph, "mem3", "b", "hi")
    assert "0300-1234567" not in model.seen[-1][-1].text and "after 5pm" in model.seen[-1][-1].text


def test_my_data_shows_only_this_lead(make_graph):
    graph, model = make_graph([call("save_lead_profile", area="E-11"), say("ok"), call("my_data"), say("E-11")])
    chat(graph, "mem4", "a", "E-11")
    out = chat(graph, "mem4", "a", "what do you know about me?")
    assert [c["name"] for c in out["tool_calls"]] == ["my_data"] and "E-11" in model.seen[-1][-2].text


def test_forget_me_asks_then_clears_only_this_lead(make_graph, repo):
    graph, model = make_graph([call("save_lead_profile", area="E-11"), say("ok"), call("save_lead_profile", area="F-7"), say("ok"),
                               call("forget_me"), say("I don't know."), say("F-7")])
    chat(graph, "gone", "a", "E-11")
    chat(graph, "stays", "a", "F-7")
    ask = chat(graph, "gone", "a", "delete everything you know about me")
    assert ask["tool_calls"] == [] and "yes" in ask["reply"].lower() and repo.leads["gone"]["area"] == "E-11"
    assert [c["name"] for c in chat(graph, "gone", "a", "yes")["tool_calls"]] == ["forget_me"]
    chat(graph, "gone", "new", "what area did I want?")
    assert "new lead" in model.seen[-1][-1].text and repo.leads["gone"].get("area") is None
    chat(graph, "stays", "new", "what area did I want?")
    assert "F-7" in model.seen[-1][-1].text


@pytest.mark.parametrize("text", ["forget my old budget, it's 4 crore now", "delete everything you know about me",
                                  "cancel my visit", "what do you know about me?", "can I see my data"])
def test_memory_requests_are_not_blocked(text):
    assert check_message(text) is None
