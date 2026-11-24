"""Pakistani money, the way leads actually type it."""
import pytest

from app.money import parse_pkr
from app.tools import calculate_installment, save_lead_profile, search_listings
from conftest import call, say
from test_graph import chat

GOOD = {"1.5 crore": 15_000_000, "dedh crore": 15_000_000, "dhai crore": 25_000_000, "paune do crore": 17_500_000,
        "sawa do crore": 22_500_000, "sarhe teen crore": 35_000_000, "80 lac": 8_000_000, "80 lakh": 8_000_000,
        "2 crore 50 lakh": 25_000_000, "85k": 85_000, "PKR 3,00,00,000": 30_000_000, "30000000": 30_000_000,
        30_000_000: 30_000_000, "aadha crore": 5_000_000, "budget 3 crore tak": 30_000_000, "ek crore": 10_000_000,
        "85 hazar per month": 85_000, "Rs. 45000": 45_000}
AMBIGUOUS = ["a lot", "2", 2, "1 to 2 crore", "50-60 lakh", "2 crore 50", "", None, True, "crore ke qareeb shayad"]


@pytest.mark.parametrize("said,pkr", GOOD.items())
def test_understands(said, pkr):
    assert parse_pkr(said) == pkr


@pytest.mark.parametrize("said", AMBIGUOUS)
def test_never_guesses(said):
    with pytest.raises(ValueError):
        parse_pkr(said)


@pytest.mark.parametrize("t,field", [(search_listings, "max_price_pkr"), (save_lead_profile, "budget_pkr"),
                                     (calculate_installment, "price_pkr")])
def test_the_model_still_sees_an_integer(t, field):
    assert "integer" in str(t.tool_call_schema.model_json_schema()["properties"][field])


def test_words_reach_the_tool_as_rupees(make_graph, repo):
    graph, _ = make_graph([call("save_lead_profile", budget_pkr="dedh crore", area="B-17"), say("Dedh crore, B-17.")])
    chat(graph, "cash1", "a", "dedh crore, B-17")
    assert repo.leads["cash1"]["budget_pkr"] == 15_000_000


def test_unclear_amount_is_returned_to_the_model_not_crashed(make_graph, repo):
    graph, model = make_graph([call("save_lead_profile", budget_pkr="2", area="B-17"), say("Do you mean 2 crore?")])
    assert chat(graph, "cash2", "a", "budget 2")["reply"] == "Do you mean 2 crore?"
    assert "lakh or crore" in model.seen[-1][-2].text and "cash2" in repo.leads and not repo.leads["cash2"].get("budget_pkr")
