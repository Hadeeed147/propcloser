"""Data access for listings, leads, visits and follow-ups.

PostgresRepo  -> Neon Postgres (production). Tables are created and seeded on startup.
MemoryRepo    -> plain Python lists (local dev without DATABASE_URL, and tests). Same interface.

Every method that touches user data takes `user_id` and filters by it: that is our isolation rule.
Listing search is shared Python logic: the catalogue is small (~30 rows) and cached in memory.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

PKT = timezone(timedelta(hours=5), "PKT")          # Pakistan has no DST
SEED_CSV = Path(__file__).resolve().parent.parent / "seed" / "listings.csv"
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "seed" / "schema.sql"
SLOT_HOURS = (11, 15, 17)                          # visit slots each day, PKT
SLOT_DAYS = 7                                      # offer the next 7 days, starting tomorrow
LEAD_FIELDS = ("name", "budget_pkr", "area", "purpose", "property_type", "beds", "timeline", "financing")


# ── formatting helpers ──

def format_pkr(amount: int | float | None) -> str:
    if amount is None:
        return "-"
    amount = float(amount)
    if amount >= 10_000_000:
        return f"{amount / 10_000_000:.2f}".rstrip("0").rstrip(".") + " crore"
    if amount >= 100_000:
        return f"{amount / 100_000:.2f}".rstrip("0").rstrip(".") + " lakh"
    return f"{amount:,.0f}"


def listing_line(listing: dict) -> str:
    rent = "/month" if listing["purpose"] == "rent" else ""
    beds = f"{listing['beds']} bed, {listing['baths']} bath | " if listing["beds"] else ""
    return (f"#{listing['id']} {listing['title']} — {listing['area']} | {beds}"
            f"{listing['size_marla']:g} marla | PKR {format_pkr(listing['price_pkr'])}{rent}")


def now_pkt() -> datetime:
    return datetime.now(PKT)


def upcoming_slots(now: datetime | None = None) -> list[datetime]:
    now = now or now_pkt()
    slots = []
    for d in range(1, SLOT_DAYS + 1):
        day = (now + timedelta(days=d)).date()
        slots += [datetime(day.year, day.month, day.day, h, tzinfo=PKT) for h in SLOT_HOURS]
    return slots


def slot_id(dt: datetime) -> str:
    return dt.astimezone(PKT).strftime("%Y-%m-%dT%H:%M")


def slot_label(dt: datetime) -> str:
    return dt.astimezone(PKT).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


def parse_slot(text: str) -> datetime:
    return datetime.strptime(text.strip()[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=PKT)


# ── listing search (shared by both repos) ──

_STOP = {"in", "the", "near", "islamabad", "sector", "area", "society", "at", "of"}


def _norm(text: str) -> str:
    return (text or "").lower().replace("-", "").replace(" ", "")


def match_area(query: str, listing: dict) -> bool:
    hay = _norm(f"{listing['area']} {listing.get('sector') or ''}")
    tokens = [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", (query or "").lower()) if t not in _STOP]
    return all(_norm(t) in hay for t in tokens) if tokens else True


def search(listings: list[dict], purpose: str = "sale", area: str | None = None, property_type: str | None = None,
           min_beds: int | None = None, max_price_pkr: int | None = None, limit: int = 5) -> tuple[list[dict], bool]:
    """Return (rows, exact). If nothing matches exactly, return the 3 closest options instead."""
    pool = [x for x in listings if x["purpose"] == (purpose or "sale")]

    def ok(x, use_area=True, use_price=True):
        return ((not area or not use_area or match_area(area, x))
                and (not property_type or x["property_type"] == property_type)
                and (not min_beds or x["beds"] >= min_beds)
                and (not max_price_pkr or not use_price or x["price_pkr"] <= max_price_pkr))

    exact = [x for x in pool if ok(x)]
    if exact:
        exact.sort(key=lambda x: -x["price_pkr"] if max_price_pkr else x["price_pkr"])   # best value under budget first
        return exact[:limit], True
    near = [x for x in pool if ok(x, use_price=False)] or [x for x in pool if ok(x, use_area=False)] or pool
    if max_price_pkr:
        near = sorted(near, key=lambda x: abs(x["price_pkr"] - max_price_pkr))
    return near[:3], False


def load_seed_listings() -> list[dict]:
    with SEED_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_clean_listing(r) for r in rows]


def _clean_listing(row: dict) -> dict:
    row = dict(row)
    for key in ("id", "beds", "baths", "price_pkr"):
        row[key] = int(row[key])
    row["size_marla"] = float(row["size_marla"] or 0)     # str from CSV, Decimal from Postgres
    return row


def lead_status(profile: dict, visits: list[dict]) -> str:
    if any(v["status"] == "confirmed" for v in visits):
        return "visit_booked"
    if profile.get("budget_pkr") and profile.get("area") and (profile.get("timeline") or profile.get("purpose")):
        return "qualified"
    return "new"


# ── in-memory repo (dev + tests) ──

class MemoryRepo:
    kind = "memory"

    def __init__(self, listings: list[dict] | None = None):
        self.listings = listings if listings is not None else load_seed_listings()
        self.leads: dict[str, dict] = {}
        self.visits: list[dict] = []
        self.followups: list[dict] = []

    async def setup(self):
        return None

    async def close(self):
        return None

    async def all_listings(self) -> list[dict]:
        return self.listings

    async def get_listing(self, listing_id: int) -> dict | None:
        return next((x for x in self.listings if x["id"] == listing_id), None)

    async def booked_slots(self, listing_id: int) -> set[datetime]:
        return {v["slot_time"] for v in self.visits if v["listing_id"] == listing_id and v["status"] == "confirmed"}

    async def create_visit(self, user_id: str, listing_id: int, slot_time: datetime) -> dict:
        visit = {"id": len(self.visits) + 1, "user_id": user_id, "listing_id": listing_id, "slot_time": slot_time,
                 "status": "pending", "created_at": now_pkt()}
        self.visits.append(visit)
        return visit

    async def confirm_visit(self, user_id: str, visit_id: int, replaces: int | None = None) -> dict | None:
        visit = next((v for v in self.visits if v["id"] == visit_id and v["user_id"] == user_id
                      and v["status"] == "pending"), None)
        if not visit or visit["slot_time"] in await self.booked_slots(visit["listing_id"]):
            return None
        visit["status"] = "confirmed"
        if replaces:
            await self.cancel_visit(user_id, replaces)
        return visit

    async def cancel_visit(self, user_id: str, visit_id: int, only_pending: bool = False) -> dict | None:
        visit = next((v for v in self.visits if v["id"] == visit_id and v["user_id"] == user_id and v["status"]
                      in (("pending",) if only_pending else ("pending", "confirmed"))), None)
        if visit:
            visit["status"] = "cancelled"
        return visit

    async def get_visit(self, user_id: str, visit_id: int) -> dict | None:
        return next((v for v in await self.user_visits(user_id) if v["id"] == visit_id), None)

    async def delete_lead(self, user_id: str):
        self.leads.pop(user_id, None)
        self.followups = [f for f in self.followups if f["user_id"] != user_id or f["status"] != "pending_approval"]

    async def followups_for(self, user_id: str) -> list[dict]:
        return [f for f in self.followups if f["user_id"] == user_id]

    async def all_leads(self) -> list[dict]:
        return list(self.leads.values())

    async def thread_ids(self, prefix: str) -> list[str]:
        return []                                   # in-memory checkpoints are found by the service directly

    async def ping(self) -> bool:
        return True

    async def spent_usd(self) -> float:
        return 0.0

    async def add_spend(self, usd: float):
        return None

    async def user_visits(self, user_id: str) -> list[dict]:
        out = []
        for v in self.visits:
            if v["user_id"] == user_id:
                listing = await self.get_listing(v["listing_id"]) or {}
                out.append({**v, "title": listing.get("title"), "area": listing.get("area")})
        return out

    async def upsert_lead(self, user_id: str, fields: dict) -> dict:
        lead = self.leads.setdefault(user_id, {"user_id": user_id, "status": "new", "created_at": now_pkt()})
        lead.update({k: v for k, v in fields.items() if k in LEAD_FIELDS and v is not None})
        lead["updated_at"] = now_pkt()
        return lead

    async def set_status(self, user_id: str, status: str):
        lead = await self.upsert_lead(user_id, {})
        lead["status"] = status

    async def add_followup(self, user_id: str, message: str, due_at: datetime) -> dict:
        item = {"id": len(self.followups) + 1, "user_id": user_id, "message": message, "due_at": due_at,
                "status": "pending_approval", "created_at": now_pkt()}
        self.followups.append(item)
        return item

    # admin (dashboard) — agency-wide views, protected by ADMIN_TOKEN in the API
    async def admin_leads(self):
        return sorted(self.leads.values(), key=lambda x: x["updated_at"], reverse=True)

    async def admin_visits(self):
        out = []
        for v in sorted(self.visits, key=lambda x: x["created_at"], reverse=True):
            listing = await self.get_listing(v["listing_id"]) or {}
            out.append({**v, "title": listing.get("title"), "area": listing.get("area")})
        return out

    async def admin_followups(self):
        return sorted(self.followups, key=lambda x: x["created_at"], reverse=True)

    async def set_followup_status(self, followup_id: int, status: str) -> dict | None:
        item = next((f for f in self.followups if f["id"] == followup_id), None)
        if item:
            item["status"] = status
        return item

    async def stats(self) -> dict:
        leads = list(self.leads.values())
        return {"leads": len(leads),
                "qualified": sum(x["status"] in ("qualified", "visit_booked") for x in leads),
                "visits_booked": sum(v["status"] == "confirmed" for v in self.visits),
                "followups_pending": sum(f["status"] == "pending_approval" for f in self.followups)}


# ── Postgres repo (Neon) ──

class PostgresRepo:
    kind = "postgres"

    def __init__(self, pool):
        self.pool = pool          # psycopg AsyncConnectionPool with autocommit + dict_row
        self._listings: list[dict] | None = None

    async def _all(self, sql: str, params=None) -> list[dict]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return await cur.fetchall()

    async def _one(self, sql: str, params=None) -> dict | None:
        rows = await self._all(sql, params)
        return rows[0] if rows else None

    async def setup(self):
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            cur = await conn.execute("select count(*) as n from listings")
            if (await cur.fetchone())["n"] == 0:
                cols = ("id", "title", "area", "sector", "property_type", "purpose", "beds", "baths",
                        "size_marla", "price_pkr", "description")
                async with conn.cursor() as c:
                    await c.executemany(
                        f"insert into listings ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                        [tuple(x[k] for k in cols) for x in load_seed_listings()])

    async def close(self):
        await self.pool.close()

    async def all_listings(self) -> list[dict]:
        if self._listings is None:
            self._listings = [_clean_listing(r) for r in await self._all("select * from listings order by id")]
        return self._listings

    async def get_listing(self, listing_id: int) -> dict | None:
        return next((x for x in await self.all_listings() if x["id"] == listing_id), None)

    async def booked_slots(self, listing_id: int) -> set[datetime]:
        rows = await self._all("select slot_time from visits where listing_id = %s and status = 'confirmed'",
                               (listing_id,))
        return {r["slot_time"] for r in rows}

    async def create_visit(self, user_id: str, listing_id: int, slot_time: datetime) -> dict:
        return await self._one(
            "insert into visits (user_id, listing_id, slot_time) values (%s, %s, %s) returning *",
            (user_id, listing_id, slot_time))

    async def confirm_visit(self, user_id: str, visit_id: int, replaces: int | None = None) -> dict | None:
        """Confirm, and for a reschedule cancel the old visit, in ONE transaction: both happen or neither does."""
        from psycopg import errors
        try:
            async with self.pool.connection() as conn, conn.transaction():
                cur = await conn.execute("update visits set status = 'confirmed' where id = %s and user_id = %s "
                                         "and status = 'pending' returning *", (visit_id, user_id))
                visit = await cur.fetchone()
                if visit and replaces:
                    await conn.execute("update visits set status = 'cancelled' where id = %s and user_id = %s",
                                       (replaces, user_id))
                return visit
        except errors.UniqueViolation:      # someone else confirmed that slot first
            return None

    async def cancel_visit(self, user_id: str, visit_id: int, only_pending: bool = False) -> dict | None:
        allowed = ["pending"] if only_pending else ["pending", "confirmed"]
        return await self._one("update visits set status = 'cancelled' where id = %s and user_id = %s "
                               "and status = any(%s) returning *", (visit_id, user_id, allowed))

    async def get_visit(self, user_id: str, visit_id: int) -> dict | None:
        return next((v for v in await self.user_visits(user_id) if v["id"] == visit_id), None)

    async def delete_lead(self, user_id: str):
        await self._all("delete from leads where user_id = %s returning user_id", (user_id,))
        await self._all("delete from followups where user_id = %s and status = 'pending_approval' returning id", (user_id,))

    async def followups_for(self, user_id: str) -> list[dict]:
        return await self._all("select * from followups where user_id = %s", (user_id,))

    async def all_leads(self) -> list[dict]:
        return await self._all("select * from leads where status <> 'visit_booked'")

    async def thread_ids(self, prefix: str) -> list[str]:
        rows = await self._all("select distinct thread_id from checkpoints where left(thread_id, %s) = %s",
                               (len(prefix), prefix))
        return [r["thread_id"] for r in rows]

    async def ping(self) -> bool:
        return bool(await self._one("select 1 as ok"))

    async def spent_usd(self) -> float:
        return float((await self._one("select coalesce(sum(usd), 0) as usd from spend"))["usd"])

    async def add_spend(self, usd: float):
        await self._all("insert into spend (day, usd) values (current_date, %s) "
                        "on conflict (day) do update set usd = spend.usd + excluded.usd returning day", (usd,))

    async def user_visits(self, user_id: str) -> list[dict]:
        return await self._all(
            "select v.*, l.title, l.area from visits v join listings l on l.id = v.listing_id "
            "where v.user_id = %s order by v.slot_time", (user_id,))

    async def upsert_lead(self, user_id: str, fields: dict) -> dict:
        fields = {k: v for k, v in fields.items() if k in LEAD_FIELDS and v is not None}
        cols = ["user_id", *fields]
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        sql = (f"insert into leads ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
               f"on conflict (user_id) do update set {updates + ', ' if updates else ''}updated_at = now() returning *")
        return await self._one(sql, (user_id, *fields.values()))

    async def set_status(self, user_id: str, status: str):
        await self._all(
            "insert into leads (user_id, status) values (%s, %s) "
            "on conflict (user_id) do update set status = excluded.status, updated_at = now() returning user_id",
            (user_id, status))

    async def add_followup(self, user_id: str, message: str, due_at: datetime) -> dict:
        return await self._one(
            "insert into followups (user_id, message, due_at) values (%s, %s, %s) returning *",
            (user_id, message, due_at))

    async def admin_leads(self):
        return await self._all("select * from leads order by updated_at desc limit 300")

    async def admin_visits(self):
        return await self._all(
            "select v.*, l.title, l.area from visits v join listings l on l.id = v.listing_id "
            "order by v.created_at desc limit 300")

    async def admin_followups(self):
        return await self._all("select * from followups order by created_at desc limit 300")

    async def set_followup_status(self, followup_id: int, status: str) -> dict | None:
        return await self._one("update followups set status = %s where id = %s returning *", (status, followup_id))

    async def stats(self) -> dict:
        return await self._one(
            "select (select count(*) from leads) as leads, "
            "(select count(*) from leads where status in ('qualified', 'visit_booked')) as qualified, "
            "(select count(*) from visits where status = 'confirmed') as visits_booked, "
            "(select count(*) from followups where status = 'pending_approval') as followups_pending")


# ── the app-wide repo instance (set once at startup) ──

_repo: MemoryRepo | PostgresRepo | None = None


def set_repo(repo) -> None:
    global _repo
    _repo = repo


def get_repo():
    global _repo
    if _repo is None:
        _repo = MemoryRepo()
    return _repo
