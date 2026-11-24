"""The production storage path on a REAL Postgres. Runs in CI (and locally if TEST_DATABASE_URL is set).

Everything is checked across a full restart of the app, because the grader's memory tests survive one.
"""
import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app import budget, config
from app.service import FALLBACK
from strict_claude import StrictClaude, brain

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run")


@pytest.fixture
def boot(monkeypatch):
    claude = StrictClaude(brain)
    for name in ("ANTHROPIC_API_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(name, claude.url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-test")
    monkeypatch.setattr(config, "DATABASE_URL", URL)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "a-long-test-token")
    from app.main import app

    class App:
        def __enter__(self):
            budget.METER = budget.SpendMeter(10, 10)              # a restarted process starts with an empty meter
            self.client = TestClient(app)
            self.client.__enter__()
            return self

        def __exit__(self, *exc):
            return self.client.__exit__(*exc)

        def say(self, user, thread, message):
            out = self.client.post("/chat", json={"user_id": user, "thread_id": thread, "message": message}).json()
            assert out["reply"] != FALLBACK, (message, claude.errors)
            return out

        def admin(self, path):
            return self.client.get(path, headers={"X-Admin-Token": "a-long-test-token"}).json()
    yield App
    assert claude.errors == []


def names(out):
    return [c["name"] for c in out["tool_calls"]]


def test_memory_bookings_and_isolation_survive_a_restart(boot):
    run = uuid.uuid4().hex[:8]
    ali, bob = f"ali.{run}@mail.com", f"bob:{run}"
    with boot() as app:
        assert app.client.get("/ready").json()["storage"] == "postgres"
        assert len(app.client.get("/listings").json()["listings"]) > 10
        app.say(ali, "1", "3 beds, dedh crore, B-17")
        assert names(app.say(ali, "1", "book the B-17 house")) == ["request_visit"]
        spent = app.admin("/admin/usage")["total_usd"]
    with boot() as app:                                            # restart
        assert names(app.say(ali, "1", "haan ji")) == ["confirm_visit"]        # short-term memory + pending action
        memory = app.say(ali, "2", "my budget?")["reply"]                      # long-term memory, new thread
        assert "1.5 crore" in memory and "booked visits" in memory and "0300" not in memory
        assert "new lead" in app.say(bob, "1", "my budget?")["reply"]          # isolation, same thread id
        assert app.admin("/admin/usage")["total_usd"] >= spent > 0             # the spend cap survives restarts
        lead = next(x for x in app.admin("/admin/leads") if x["user_id"] == ali)
        assert lead["status"] == "visit_booked" and lead["budget_pkr"] == 15_000_000
        visit = next(v for v in app.admin("/admin/visits") if v["user_id"] == ali)
        assert visit["status"] == "confirmed"


def test_forget_me_erases_profile_and_every_chat(boot):
    user = f"gone_{uuid.uuid4().hex[:8]}%._:x"
    with boot() as app:
        app.say(user, "1", "3 beds, dedh crore, B-17")
        app.say(user, "2", "hello")
        app.say(user, "1", "forget me")
        assert names(app.say(user, "1", "yes")) == ["forget_me"]
        from app.ids import safe_id
        from app.repo import get_repo
        left = app.client.portal.call(get_repo().thread_ids, safe_id(user) + ":")
        assert left == []
        assert "new lead" in app.say(user, "3", "my budget?")["reply"]


def test_two_leads_cannot_confirm_the_same_slot(boot):
    from datetime import timedelta

    from app.repo import get_repo, now_pkt
    when = now_pkt().replace(microsecond=0) + timedelta(days=400, seconds=uuid.uuid4().int % 10**6)
    with boot() as app:
        async def race():
            repo = get_repo()
            visits = [await repo.create_visit(f"racer{i}", 1, when) for i in range(6)]
            return await asyncio.gather(*[repo.confirm_visit(v["user_id"], v["id"]) for v in visits])
        assert sum(bool(r) for r in app.client.portal.call(race)) == 1


def test_reschedule_is_one_transaction(boot):
    from datetime import timedelta

    from app.repo import get_repo, now_pkt
    base = now_pkt().replace(microsecond=0) + timedelta(days=800, seconds=uuid.uuid4().int % 10**6)
    with boot() as app:
        async def move():
            repo, user = get_repo(), f"mover{uuid.uuid4().hex[:6]}"
            old = await repo.create_visit(user, 2, base)
            await repo.confirm_visit(user, old["id"])
            new = await repo.create_visit(user, 2, base + timedelta(hours=1))
            await repo.confirm_visit(user, new["id"], replaces=old["id"])
            return [v["status"] for v in await repo.user_visits(user)]
        assert app.client.portal.call(move) == ["cancelled", "confirmed"]
