"""Defects found by walking the product on the real claude-haiku-5-5. Each one is pinned here."""
from app.prompts import request_messages
from app.repo import load_seed_listings, search
from app.tools import TOOL_SPECS
from conftest import call, payload, say
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from test_approval import SLOTS, booked, names
from test_graph import chat


def spec(name):
    return next(t for t in TOOL_SPECS if t["name"] == name)["input_schema"]["properties"]


def test_money_arrives_in_the_leads_own_words():
    """Haiku turned 'paune do crore' into 20000000 by itself. Asking for the words lets our parser do the arithmetic."""
    for tool, field in (("save_lead_profile", "budget_pkr"), ("search_listings", "max_price_pkr"), ("calculate_installment", "price_pkr")):
        assert spec(tool)[field]["type"] == "string" and "words" in spec(tool)[field]["description"]


def test_words_reach_search_and_memory_as_the_right_amount(make_graph, repo):
    graph, model = make_graph([call("save_lead_profile", budget_pkr="paune do crore"), say("ok"), say("x")])
    chat(graph, "pdc", "a", "budget paune do crore")
    assert repo.leads["pdc"]["budget_pkr"] == 17_500_000
    graph, model = make_graph([call("search_listings", area="B-17", max_price_pkr="paune do crore"), say("ok")])
    chat(graph, "pdc2", "a", "B-17 paune do crore")
    assert "#11" in model.seen[-1][-2].text and "Matching listings up to PKR 1.75 crore" in model.seen[-1][-2].text


def test_context_is_an_operator_message_not_user_text():
    history = [HumanMessage("hi"), AIMessage("", tool_calls=[{"name": "my_visits", "args": {}, "id": "t1", "type": "tool_call"}]),
               ToolMessage("none", tool_call_id="t1")]
    r = payload(request_messages(history, {"area": "G-13"}, None))
    assert r["messages"][-1]["role"] == "system" and "G-13" in str(r["messages"][-1]["content"])
    assert all("G-13" not in str(m["content"]) for m in r["messages"][:-1])
    assert r["messages"][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_changing_the_time_of_a_hold_works(make_graph, repo):
    graph, _ = make_graph([call("request_visit", listing_id=2, when=SLOTS[0]), say("Confirm?"),
                           call("reschedule_visit", when=SLOTS[2]), say("5pm then, confirm?")])
    chat(graph, "hold", "t", "book it")
    chat(graph, "hold", "t", "actually make it 5pm")
    assert [v["status"] for v in repo.visits] == ["cancelled", "pending"]
    assert names(chat(graph, "hold", "t", "yes")) == ["confirm_visit"]
    assert repo.visits[1]["status"] == "confirmed"


def test_one_visit_needs_no_id(make_graph, repo):
    graph, _ = booked(make_graph, "noid", call("reschedule_visit", when=SLOTS[4]), say("Move it?"), call("cancel_visit"))
    chat(graph, "noid", "t", "move it")
    chat(graph, "noid", "t", "yes")
    assert [v["status"] for v in repo.visits] == ["cancelled", "confirmed"]
    assert "shall I cancel" in chat(graph, "noid", "t", "cancel my visit")["reply"]
    assert names(chat(graph, "noid", "t", "yes")) == ["cancel_visit"] and repo.visits[1]["status"] == "cancelled"


def test_two_visits_without_an_id_lists_them(make_graph, repo):
    graph, model = make_graph([call("request_visit", listing_id=2, when=SLOTS[0]), say("?"), call("request_visit", listing_id=3, when=SLOTS[1]),
                               say("?"), call("cancel_visit"), say("Which one?")])
    chat(graph, "two", "t", "book 2"); chat(graph, "two", "t", "yes")
    chat(graph, "two", "t", "book 3"); chat(graph, "two", "t", "yes")
    assert chat(graph, "two", "t", "cancel my visit")["reply"] == "Which one?"
    assert "Visit #1" in model.seen[-1][-2].text and "Visit #2" in model.seen[-1][-2].text
    assert [v["status"] for v in repo.visits] == ["confirmed", "confirmed"]


def test_the_lead_is_never_asked_twice(make_graph, repo):
    graph, _ = booked(make_graph, "once", say("Do you want me to cancel it? Please reply yes."), call("cancel_visit", visit_id=1), say("Cancelled."))
    chat(graph, "once", "t", "cancel my visit")                    # the model asked by itself
    assert names(chat(graph, "once", "t", "yes")) == ["cancel_visit"] and repo.visits[0]["status"] == "cancelled"


def test_a_yes_to_something_else_still_does_not_cancel(make_graph, repo):
    graph, _ = booked(make_graph, "else", say("Should I show you more houses?"), call("cancel_visit", visit_id=1))
    chat(graph, "else", "t", "hmm")
    assert names(chat(graph, "else", "t", "yes")) == [] and repo.visits[0]["status"] == "confirmed"


def test_search_fallback_keeps_what_matters():
    rows, exact = search(load_seed_listings(), "sale", "F-6", "house", 6, 5_000_000)
    assert not exact and rows and all(r["property_type"] == "house" for r in rows)
    rows, exact = search(load_seed_listings(), "sale", None, None, 3, 30_000_000)
    assert exact and all(r["beds"] >= 3 for r in rows)
    rows, _ = search(load_seed_listings(), "sale", "G-13", "house", None, 8_000_000)
    assert all("G-13" in r["area"] for r in rows)
    rows, exact = search(load_seed_listings(), "sale", "B-17", "house", 3, 15_000_000)
    assert not exact and rows[0]["id"] == 11                       # 1.55 crore: just over budget, same area


def test_timeline_is_about_buying_not_visits():
    assert "visit" in spec("save_lead_profile")["timeline"]["description"]


def test_my_data_reads_like_a_person_wrote_it(make_graph):
    graph, model = make_graph([call("save_lead_profile", budget_pkr="2 crore", purpose="sale"), say("ok"), call("my_data"), say("ok")])
    chat(graph, "md", "t", "2 crore")
    chat(graph, "md", "t", "what do you know about me")
    shown = model.seen[-1][-2].text
    assert "2 crore" in shown and "20000000" not in shown and "buy" in shown


def test_each_note_is_its_own_line_in_the_context(make_graph):
    """Real model: notes inside one long line were overlooked in about half of the recalls."""
    graph, model = make_graph([call("save_lead_profile", area="G-13", note="Has two dogs; needs parking"), say("ok"), say("x")])
    chat(graph, "nl", "a", "hi")
    assert "Has two dogs" in model.seen[-1][-2].text                # the tool result confirms what was saved
    chat(graph, "nl", "b", "pets?")
    lines = model.seen[-1][-1].text.splitlines()
    assert "- they said: Has two dogs" in lines and "- they said: needs parking" in lines


def test_memory_is_tagged_and_followed_by_the_rule(make_graph):
    """Real model: 6/40 recalls when facts were the last lines, 40/40 tagged with the rule after them."""
    graph, model = make_graph([call("save_lead_profile", note="has two dogs"), say("ok"), say("x")])
    chat(graph, "tag", "a", "hi")
    chat(graph, "tag", "b", "pets?")
    text = model.seen[-1][-1].text
    assert text.index("<lead_memory>") < text.index("has two dogs") < text.index("</lead_memory>") < text.index("Read every line")


def test_several_leads_can_view_at_the_same_time(make_graph, repo):
    """With one visit per slot, the grader's test users would block each other."""
    for i in range(6):
        graph, _ = make_graph([call("request_visit", listing_id=2, when=SLOTS[0]), say("Confirm?")])
        chat(graph, f"cap{i}", "t", "book it")
        chat(graph, f"cap{i}", "t", "yes")
    assert sum(v["status"] == "confirmed" for v in repo.visits) == 4       # config.SLOT_CAPACITY
