"""Ghosted-lead sweep: "follows up for days" without spending a token.

Leads who went quiet get a personal draft built from their long-term profile and a REAL matching listing. A draft only
enters the approval queue (status pending_approval): a human at the agency approves it. Nothing is ever sent from here.
"""
from datetime import datetime, timedelta

from app.repo import format_pkr, listing_line, now_pkt, search

STEPS_AFTER = (timedelta(days=3), timedelta(days=7))       # 2nd and 3rd follow-up, counted from the lead's last message


def draft(lead: dict, matches: list[dict]) -> str:
    hello = f"Salam {lead['name']}!" if lead.get("name") else "Salam!"
    kind = lead.get("property_type") or "property"
    beds = f"{lead['beds']}-bed " if lead.get("beds") else ""
    where = f" in {lead['area']}" if lead.get("area") else ""
    budget = f" around PKR {format_pkr(lead['budget_pkr'])}" if lead.get("budget_pkr") else ""
    offer = f" This one fits: {listing_line(matches[0])}." if matches else " We are still looking for the right match."
    return f"{hello} You were looking for a {beds}{kind}{where}{budget}.{offer} Would you like to visit this week?"


async def sweep(repo, idle_hours: float = 24, now: datetime | None = None) -> list[dict]:
    now = now or now_pkt()
    waits = (timedelta(hours=idle_hours), *STEPS_AFTER)
    listings = await repo.all_listings()
    drafted = []
    for lead in await repo.all_leads():
        if lead["status"] == "visit_booked" or not (lead.get("area") or lead.get("budget_pkr")):
            continue
        if now - lead["updated_at"] < waits[0]:
            continue
        mine = [f for f in await repo.followups_for(lead["user_id"]) if f["created_at"] >= lead["updated_at"]]
        if len(mine) >= len(waits) or any(f["status"] == "pending_approval" for f in mine):
            continue
        if now - lead["updated_at"] < waits[len(mine)]:
            continue
        rows, exact = search(listings, lead.get("purpose") or "sale", lead.get("area"), lead.get("property_type"),
                             lead.get("beds"), lead.get("budget_pkr"), limit=1)
        drafted.append(await repo.add_followup(lead["user_id"], draft(lead, rows if exact else []), now))
    return drafted
