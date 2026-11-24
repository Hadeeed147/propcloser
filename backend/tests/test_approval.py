"""Parallel tool calls, the approval gate, the exact-yes fast path, cancel and reschedule."""
import asyncio

import pytest
from langchain_core.messages import HumanMessage

from app.approval import is_exact_yes, is_yes
from app.prompts import system_message
from app.repo import slot_id, upcoming_slots
from app.service import FALLBACK, thread_key
from conftest import assert_tool_calls_answered, call, payload, say, two_calls
from test_graph import chat

SLOTS = [slot_id(s) for s in upcoming_slots()]


def names(out):
    return [c["name"] for c in out["tool_calls"]]


def history(graph, user, thread):
    cfg = {"configurable": {"thread_id": thread_key(user, thread)}}
    return asyncio.run(graph.aget_state(cfg)).values["messages"]


def assert_claude_would_accept(graph, user, thread):
    msgs = history(graph, user, thread)
    assert_tool_calls_answered(payload([system_message({}, None), *msgs, HumanMessage("next")]))


# ── several tools in one message ──

def test_two_saves_in_one_message_both_apply(make_graph):
    graph, model = make_graph([two_calls(("save_lead_profile", {"area": "G-13"}), ("save_lead_profile", {"beds": 3})),
                               say("Noted."), say("G-13, 3 beds.")])
    assert chat(graph, "par1", "a", "3 beds in G-13")["reply"] == "Noted."
    chat(graph, "par1", "b", "what did I want?")
    memory = model.seen[-1][0].text
    assert "area: G-13" in memory and "beds: 3" in memory


def test_save_and_hold_in_one_message(make_graph, repo):
    graph, model = make_graph([two_calls(("save_lead_profile", {"area": "Bahria Town"}),
                                         ("request_visit", {"listing_id": 2, "slot": SLOTS[0]})), say("Shall I book?")])
    out = chat(graph, "par2", "a", "Bahria, book listing 2 on the first slot")
    assert out["reply"] == "Shall I book?" and repo.visits[0]["status"] == "pending"
    assert repo.leads["par2"]["area"] == "Bahria Town"


def test_safe_and_risky_calls_mixed_keeps_history_valid(make_graph, repo):
    graph, _ = make_graph([two_calls(("my_visits", {}), ("confirm_visit", {})), say("You have no visits yet.")])
    out = chat(graph, "mix", "a", "confirm my booking")
    assert names(out) == ["my_visits"] and repo.visits == []
    assert_claude_would_accept(graph, "mix", "a")


# ── what counts as a yes ──

@pytest.mark.parametrize("text", ["yes", "Yes please!", "haan ji", "theek hai, kar do", "ok confirm", "Yes, book it.",
                                  "go ahead", "JI", "sure, thanks"])
def test_exact_yes(text):
    assert is_exact_yes(text)


@pytest.mark.parametrize("text", ["ok show me cheaper ones", "yes but Sunday", "no", "yes?", "", "book", "yes cancel it",
                                  "nahi", "what time", "please", "thanks", "it"])
def test_not_an_exact_yes(text):
    assert not is_exact_yes(text)


def test_loose_yes_depends_on_the_action():
    assert is_yes("yes, cancel it", "cancel_visit") and not is_yes("yes, cancel it", "confirm_visit")
    assert not is_yes("yes but make it Sunday", "confirm_visit") and not is_yes("no thanks", "confirm_visit")


# ── booking ──

def hold(graph, user, thread="t", listing=2, slot=None):
    return chat(graph, user, thread, "book it on the first slot please")


def test_yes_books_with_one_model_call(make_graph, repo):
    graph, model = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Shall I confirm?"),
                               say("Booked!"), say("It is already booked.")])
    hold(graph, "y1")
    before = len(model.seen)
    out = chat(graph, "y1", "t", "haan ji")
    assert names(out) == ["confirm_visit"] and out["reply"] == "Booked!" and len(model.seen) - before == 1
    assert repo.visits[0]["status"] == "confirmed"
    again = chat(graph, "y1", "t", "yes")                          # retry / double tap
    assert names(again) == [] and [v["status"] for v in repo.visits] == ["confirmed"]
    assert_claude_would_accept(graph, "y1", "t")


def test_not_a_yes_does_not_book(make_graph, repo):
    graph, _ = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Shall I confirm?"),
                           say("Here are cheaper ones.")])
    hold(graph, "n1")
    chat(graph, "n1", "t", "ok show me cheaper ones")
    assert repo.visits[0]["status"] == "pending"


def test_yes_to_a_different_question_does_not_book(make_graph, repo):
    graph, _ = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Shall I confirm?"),
                           say("Should I also search G-13?"), call("search_listings", area="G-13"), say("Here is G-13.")])
    hold(graph, "d1")
    chat(graph, "d1", "t", "what about other areas")
    out = chat(graph, "d1", "t", "yes")                             # answers the G-13 question, not the booking
    assert names(out) == ["search_listings"] and repo.visits[0]["status"] == "pending"


def test_slot_taken_before_the_yes(make_graph, repo):
    graph, _ = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Confirm?"),
                           call("request_visit", listing_id=2, slot=SLOTS[0]), say("Confirm?"),
                           say("Booked!"), say("Sorry, that slot just went.")])
    hold(graph, "s1")
    hold(graph, "s2")
    chat(graph, "s1", "t", "yes")
    chat(graph, "s2", "t", "yes")
    assert {v["user_id"]: v["status"] for v in repo.visits} == {"s1": "confirmed", "s2": "pending"}


def test_a_new_hold_replaces_the_old_one(make_graph, repo):
    graph, _ = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Confirm?"),
                           call("request_visit", listing_id=2, slot=SLOTS[1]), say("Confirm the new time?")])
    hold(graph, "r1")
    chat(graph, "r1", "t", "actually the next slot")
    assert [v["status"] for v in repo.visits] == ["cancelled", "pending"]


# ── cancel and reschedule ──

def booked(make_graph, user, *more):
    graph, model = make_graph([call("request_visit", listing_id=2, slot=SLOTS[0]), say("Confirm?"), say("Booked!"), *more])
    hold(graph, user)
    chat(graph, user, "t", "yes")
    return graph, model


def test_cancel_asks_first_then_cancels(make_graph, repo):
    graph, _ = booked(make_graph, "c1", call("cancel_visit", visit_id=1), say("Cancelled."))
    out = chat(graph, "c1", "t", "cancel my visit")
    assert names(out) == [] and "cancel" in out["reply"].lower() and repo.visits[0]["status"] == "confirmed"
    out = chat(graph, "c1", "t", "yes")
    assert names(out) == ["cancel_visit"] and repo.visits[0]["status"] == "cancelled"
    assert asyncio.run(repo.booked_slots(2)) == set()               # the slot is free again
    assert_claude_would_accept(graph, "c1", "t")


def test_cannot_cancel_someone_elses_visit(make_graph, repo):
    booked(make_graph, "owner")
    graph, _ = make_graph([call("cancel_visit", visit_id=1), say("I can't find that visit.")])
    out = chat(graph, "thief", "t", "cancel visit 1")
    assert out["reply"] == "I can't find that visit." and repo.visits[0]["status"] == "confirmed"


def test_reschedule_swaps_only_after_yes(make_graph, repo):
    graph, _ = booked(make_graph, "m1", call("reschedule_visit", visit_id=1, slot=SLOTS[4]), say("Move it?"), say("Moved."))
    chat(graph, "m1", "t", "move my visit")
    assert [v["status"] for v in repo.visits] == ["confirmed", "pending"]
    chat(graph, "m1", "t", "yes")
    assert [(v["status"], slot_id(v["slot_time"])) for v in repo.visits] == [("cancelled", SLOTS[0]), ("confirmed", SLOTS[4])]


def test_no_fallbacks_anywhere(make_graph):
    graph, _ = booked(make_graph, "z1", say("ok"))
    assert all(m.text != FALLBACK for m in history(graph, "z1", "t"))
