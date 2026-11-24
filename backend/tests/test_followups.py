"""The ghosted-lead sweep: drafts for leads who went quiet. No model, never sends."""
import asyncio
from datetime import timedelta

from app.followups import sweep
from app.repo import now_pkt, parse_slot, slot_id, upcoming_slots

run = asyncio.run


def lead(repo, user, **fields):
    run(repo.upsert_lead(user, fields))
    run(repo.set_status(user, "qualified"))


def later(**kw):
    return now_pkt() + timedelta(**kw)


def test_idle_lead_gets_a_personal_draft_waiting_for_approval(repo):
    lead(repo, "q", name="Ali", area="Bahria Town", property_type="house", beds=3, budget_pkr=30_000_000, purpose="sale")
    drafted = run(sweep(repo, now=later(hours=25)))
    assert len(drafted) == 1 and drafted[0]["status"] == "pending_approval" and drafted[0]["user_id"] == "q"
    text = drafted[0]["message"]
    assert "Ali" in text and "Bahria Town" in text and "3 crore" in text and "#2 7 Marla Family House" in text


def test_second_sweep_drafts_nothing_new(repo):
    lead(repo, "q", area="G-13")
    assert len(run(sweep(repo, now=later(hours=25)))) == 1
    assert run(sweep(repo, now=later(hours=26))) == []


def test_skips_active_booked_and_empty_leads(repo):
    lead(repo, "active", area="G-13")
    assert run(sweep(repo, now=later(hours=2))) == []
    repo.leads.clear()
    lead(repo, "booked", area="G-13")
    run(repo.set_status("booked", "visit_booked"))
    run(repo.set_status("empty", "new"))
    assert run(sweep(repo, now=later(days=3))) == []


def test_at_most_three_spaced_out(repo):
    lead(repo, "quiet", area="G-13")
    sent = []
    for day in (1.1, 2, 3.1, 5, 7.1, 20):
        for item in run(sweep(repo, now=later(days=day))):
            sent.append(day)
            run(repo.set_followup_status(item["id"], "approved"))
    assert sent == [1.1, 3.1, 7.1]


def test_replying_resets_the_sequence(repo):
    lead(repo, "back", area="G-13")
    item = run(sweep(repo, now=later(hours=25)))[0]
    run(repo.set_followup_status(item["id"], "approved"))
    item["created_at"] = now_pkt() - timedelta(days=2)                  # the draft is old, then the lead replied
    run(repo.set_status("back", "qualified"))
    assert len(run(sweep(repo, now=later(hours=25)))) == 1


def test_admin_route_needs_the_token(repo):
    from fastapi.testclient import TestClient
    from app import config
    from app.main import app
    with TestClient(app) as c:
        assert c.post("/admin/sweep").status_code == 401
        r = c.post("/admin/sweep", headers={"X-Admin-Token": config.ADMIN_TOKEN})
        assert r.status_code == 200 and r.json() == {"drafted": []}
