"""The agent's tools. Every tool reads the lead's identity from runtime.context (set by the API),
never from a model argument, so one lead can never read or write another lead's data.

Long-term memory lives in the LangGraph Store under ("leads", user_id) -> "profile".
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.context import Ctx
from app.repo import (format_pkr, get_repo, listing_line, now_pkt, parse_slot, search, slot_id, slot_label,
                      upcoming_slots)

PROFILE_KEY = "profile"
RISKY_TOOLS = {"confirm_visit"}          # must pass the approval_gate node


def memory_namespace(user_id: str) -> tuple[str, str]:
    return ("leads", user_id)


async def read_profile(store, user_id: str) -> dict:
    item = await store.aget(memory_namespace(user_id), PROFILE_KEY) if store else None
    return dict(item.value) if item else {}


# ── search ──

@tool
async def search_listings(purpose: Literal["sale", "rent"] = "sale", area: Optional[str] = None,
                          property_type: Optional[Literal["house", "flat", "plot"]] = None,
                          min_beds: Optional[int] = None, max_price_pkr: Optional[int] = None) -> str:
    """Search the agency's Islamabad listings.
    Prices are full PKR: 1 crore = 10,000,000 and 1 lakh = 100,000. For rent, max_price_pkr is the monthly rent.
    area examples: 'Bahria Town', 'DHA Phase 2', 'G-13', 'F-11', 'B-17'."""
    rows, exact = search(await get_repo().all_listings(), purpose, area, property_type, min_beds, max_price_pkr)
    if not rows:
        return "No listings found."
    head = "Matching listings:" if exact else "No exact match. Closest options:"
    return head + "\n" + "\n".join(listing_line(r) for r in rows)


@tool
async def get_listing(listing_id: int) -> str:
    """Get full details of one listing by its id (the number after #)."""
    listing = await get_repo().get_listing(listing_id)
    if not listing:
        return f"No listing #{listing_id}."
    return f"{listing_line(listing)}\nSector: {listing.get('sector') or '-'}\n{listing.get('description') or ''}"


@tool
async def check_slots(listing_id: int) -> str:
    """List free site-visit slots for a listing. Pass a slot id from here to request_visit."""
    repo = get_repo()
    if not await repo.get_listing(listing_id):
        return f"No listing #{listing_id}."
    taken = await repo.booked_slots(listing_id)
    free = [s for s in upcoming_slots() if s not in taken][:6]
    if not free:
        return "No free slots in the next 7 days."
    return f"Free visit slots for #{listing_id} (slot id, then time):\n" + \
        "\n".join(f"{slot_id(s)} ({slot_label(s)})" for s in free)


@tool
def calculate_installment(price_pkr: int, down_payment_pct: float = 20, years: int = 10,
                          annual_rate_pct: float = 12) -> str:
    """Estimate the monthly installment for buying a property with a bank or developer plan."""
    if price_pkr <= 0 or years <= 0 or not 0 <= down_payment_pct < 100:
        return "Please give a positive price, a down payment between 0 and 99%, and at least 1 year."
    loan = price_pkr * (1 - down_payment_pct / 100)
    r, n = annual_rate_pct / 100 / 12, years * 12
    monthly = loan * r / (1 - (1 + r) ** -n) if r else loan / n
    return (f"Down payment PKR {format_pkr(price_pkr - loan)}, financed PKR {format_pkr(loan)}. "
            f"Monthly installment ≈ PKR {monthly:,.0f} for {years} years at {annual_rate_pct:g}% (estimate).")


# ── long-term memory ──

@tool
async def save_lead_profile(runtime: ToolRuntime[Ctx], name: Optional[str] = None, budget_pkr: Optional[int] = None,
                            area: Optional[str] = None, purpose: Optional[Literal["sale", "rent"]] = None,
                            property_type: Optional[Literal["house", "flat", "plot"]] = None,
                            beds: Optional[int] = None, timeline: Optional[str] = None,
                            financing: Optional[str] = None) -> Command:
    """Save facts the lead tells you (only the ones they said). Call it as soon as you learn any of them.
    budget_pkr is full PKR (monthly rent if renting). Never save phone numbers, CNIC or payment details."""
    fields = {"name": name, "budget_pkr": budget_pkr, "area": area, "purpose": purpose,
              "property_type": property_type, "beds": beds, "timeline": timeline, "financing": financing}
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    if "name" in fields and any(ch.isdigit() for ch in str(fields["name"])):
        fields.pop("name")                                   # never store numbers as a name
    user_id = runtime.context.user_id
    profile = {**await read_profile(runtime.store, user_id), **fields}
    await runtime.store.aput(memory_namespace(user_id), PROFILE_KEY, profile)
    await get_repo().upsert_lead(user_id, fields)
    return Command(update={
        "lead_profile": profile,
        "messages": [ToolMessage(f"Saved: {fields or 'nothing new'}", tool_call_id=runtime.tool_call_id)],
    })


# ── visits (human approval required) ──

@tool
async def request_visit(listing_id: int, slot: str, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Hold a site-visit slot (status pending). slot is a slot id from check_slots, e.g. 2026-11-28T15:00.
    After this, ask the lead to confirm. Do NOT call confirm_visit until they say yes."""
    repo = get_repo()
    listing = await repo.get_listing(listing_id)
    if not listing:
        return f"No listing #{listing_id}."
    try:
        when = parse_slot(slot)
    except ValueError:
        return "Invalid slot. Call check_slots and pass a slot id exactly, e.g. 2026-11-28T15:00."
    if when not in upcoming_slots() or when in await repo.booked_slots(listing_id):
        return "That slot is not available. Call check_slots for free slots."
    visit = await repo.create_visit(runtime.context.user_id, listing_id, when)
    summary = f"a visit to #{listing_id} {listing['title']} ({listing['area']}) on {slot_label(when)}"
    # Remember which user message created the hold: the confirming "yes" must come in a later message.
    human_turn = sum(isinstance(m, HumanMessage) for m in (runtime.state or {}).get("messages", []))
    return Command(update={
        "pending_action": {"type": "visit", "visit_id": visit["id"], "summary": summary, "human_turn": human_turn},
        "messages": [ToolMessage(f"Held {summary} (pending). Ask the lead to confirm it. "
                                 "Do not call confirm_visit until they say yes.", tool_call_id=runtime.tool_call_id)],
    })


@tool
async def confirm_visit(runtime: ToolRuntime[Ctx]) -> Command | str:
    """Book the pending visit. Only call this after the lead clearly says yes to the pending visit."""
    pending = (runtime.state or {}).get("pending_action")
    if not pending:
        return "There is no pending visit to confirm. Use check_slots and request_visit first."
    user_id = runtime.context.user_id
    visit = await get_repo().confirm_visit(user_id, pending["visit_id"])
    if not visit:
        return Command(update={"pending_action": None, "messages": [ToolMessage(
            "That slot was just taken or expired. Offer the lead other slots.", tool_call_id=runtime.tool_call_id)]})
    profile = await read_profile(runtime.store, user_id)
    profile["booked_visits"] = (profile.get("booked_visits", []) + [pending["summary"]])[-5:]
    await runtime.store.aput(memory_namespace(user_id), PROFILE_KEY, profile)
    return Command(update={
        "pending_action": None,
        "lead_profile": profile,
        "messages": [ToolMessage(f"Confirmed {pending['summary']} (visit #{visit['id']}).",
                                 tool_call_id=runtime.tool_call_id)],
    })


@tool
async def my_visits(runtime: ToolRuntime[Ctx]) -> str:
    """List this lead's own site visits (pending and confirmed)."""
    visits = await get_repo().user_visits(runtime.context.user_id)
    if not visits:
        return "This lead has no visits yet."
    return "\n".join(f"Visit #{v['id']}: #{v['listing_id']} {v['title']} ({v['area']}) on "
                     f"{slot_label(v['slot_time'])} — {v['status']}" for v in visits)


@tool
async def schedule_followup(message: str, runtime: ToolRuntime[Ctx], due_in_days: int = 2) -> str:
    """Queue a follow-up message to this lead. It is NOT sent: the agency approves it on the dashboard first."""
    due = now_pkt() + timedelta(days=max(1, min(due_in_days, 30)))
    item = await get_repo().add_followup(runtime.context.user_id, message[:500], due)
    return f"Follow-up #{item['id']} queued for agency approval (due {due:%d %b}). It has not been sent."


TOOLS = [search_listings, get_listing, check_slots, calculate_installment, save_lead_profile,
         request_visit, confirm_visit, my_visits, schedule_followup]
