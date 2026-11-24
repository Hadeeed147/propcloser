"""The agent's tools. Every tool reads the lead's identity from runtime.context (set by the API),
never from a model argument, so one lead can never read or write another lead's data.

Long-term memory lives in the LangGraph Store under ("leads", user_id) -> "profile".
Tools that change the graph's state return a Command (same pattern as the instructor's verify_identity).
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Literal, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BeforeValidator

from app.context import Ctx
from app.money import parse_pkr
from app.privacy import redact
from app.repo import (format_pkr, get_repo, listing_line, now_pkt, parse_slot, search, slot_id, slot_label,
                      upcoming_slots)

PROFILE_KEY = "profile"
RISKY_TOOLS = {"confirm_visit", "cancel_visit", "forget_me"}      # must pass the approval_gate node
MAX_NOTES = 8

# The model sees a plain integer; people's words ("dedh crore") are still understood if it passes them through.
Pkr = Annotated[int, BeforeValidator(parse_pkr)]

_profile_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)   # two saves in one message must not overwrite


def memory_namespace(user_id: str) -> tuple[str, str]:
    return ("leads", user_id)


async def read_profile(store, user_id: str) -> dict:
    item = await store.aget(memory_namespace(user_id), PROFILE_KEY) if store else None
    return dict(item.value) if item else {}


def visit_label(visit: dict) -> str:
    return f"#{visit['listing_id']} {visit['title']} ({visit['area']}) on {slot_label(visit['slot_time'])}"


async def full_memory(store, user_id: str) -> dict:
    """The saved profile plus the lead's confirmed upcoming visits (from the database, so never out of date)."""
    profile = await read_profile(store, user_id)
    visits = [visit_label(v) for v in await get_repo().user_visits(user_id)
              if v["status"] == "confirmed" and v["slot_time"] > now_pkt()]
    return {**profile, "booked_visits": visits} if visits else profile


# ── search ──

@tool
async def search_listings(purpose: Literal["sale", "rent"] = "sale", area: Optional[str] = None,
                          property_type: Optional[Literal["house", "flat", "plot"]] = None,
                          min_beds: Optional[int] = None, max_price_pkr: Optional[Pkr] = None) -> str:
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
    """List free site-visit slots for a listing. Pass a slot id from here to request_visit or reschedule_visit."""
    repo = get_repo()
    if not await repo.get_listing(listing_id):
        return f"No listing #{listing_id}."
    taken = await repo.booked_slots(listing_id)
    free = [s for s in upcoming_slots() if s not in taken]
    if not free:
        return "No free slots in the next 7 days."
    return f"Free visit slots for #{listing_id} (slot id, then time):\n" + \
        "\n".join(f"{slot_id(s)} ({slot_label(s)})" for s in free)


@tool
def calculate_installment(price_pkr: Pkr, down_payment_pct: float = 20, years: int = 10,
                          annual_rate_pct: float = 12) -> str:
    """Estimate the monthly installment for buying a property with a bank or developer plan."""
    if years <= 0 or not 0 <= down_payment_pct < 100:
        return "Please give a down payment between 0 and 99%, and at least 1 year."
    loan = price_pkr * (1 - down_payment_pct / 100)
    r, n = annual_rate_pct / 100 / 12, years * 12
    monthly = loan * r / (1 - (1 + r) ** -n) if r else loan / n
    return (f"Down payment PKR {format_pkr(price_pkr - loan)}, financed PKR {format_pkr(loan)}. "
            f"Monthly installment ≈ PKR {monthly:,.0f} for {years} years at {annual_rate_pct:g}% (estimate).")


# ── long-term memory ──

@tool
async def save_lead_profile(runtime: ToolRuntime[Ctx], name: Optional[str] = None, budget_pkr: Optional[Pkr] = None,
                            area: Optional[str] = None, purpose: Optional[Literal["sale", "rent"]] = None,
                            property_type: Optional[Literal["house", "flat", "plot"]] = None,
                            beds: Optional[int] = None, timeline: Optional[str] = None,
                            financing: Optional[str] = None, note: Optional[str] = None) -> str:
    """Save facts the lead tells you (only the ones they said). Call it as soon as you learn any of them.
    budget_pkr is full PKR (monthly rent if renting). note: one other lasting fact, e.g. 'needs parking for 2 cars'.
    Never save phone numbers, CNIC or payment details."""
    given = {"name": name, "budget_pkr": budget_pkr, "area": area, "purpose": purpose,
             "property_type": property_type, "beds": beds, "timeline": timeline, "financing": financing}
    fields = {k: redact(v) if isinstance(v, str) else v for k, v in given.items() if v not in (None, "")}
    user_id = runtime.context.user_id
    async with _profile_locks[user_id]:
        profile = {**await read_profile(runtime.store, user_id), **fields}
        if note:
            notes = [n for n in profile.get("notes", []) if n != redact(note)] + [redact(note)]
            profile["notes"] = notes[-MAX_NOTES:]
        await runtime.store.aput(memory_namespace(user_id), PROFILE_KEY, profile)
        await get_repo().upsert_lead(user_id, fields)
    return f"Saved: {fields}" + (f", note: {redact(note)}" if note else "")


@tool
async def my_data(runtime: ToolRuntime[Ctx]) -> str:
    """Show the lead everything remembered about them. Use when they ask what you know about them."""
    memory = await full_memory(runtime.store, runtime.context.user_id)
    return "\n".join(f"- {k.replace('_', ' ')}: {'; '.join(v) if isinstance(v, list) else v}"
                     for k, v in memory.items()) or "Nothing is saved about this lead."


@tool
async def forget_me(runtime: ToolRuntime[Ctx]) -> str:
    """Delete everything remembered about the lead. Only when they clearly ask you to delete or forget their data.
    If they only want to change one fact, use save_lead_profile instead."""
    user_id = runtime.context.user_id
    async with _profile_locks[user_id]:
        await runtime.store.adelete(memory_namespace(user_id), PROFILE_KEY)
        await get_repo().delete_lead(user_id)
    return "Deleted the saved profile. Booked visits stay on the calendar until cancelled."


# ── visits (human approval required) ──

def human_turn(runtime) -> int:
    return sum(isinstance(m, HumanMessage) for m in (runtime.state or {}).get("messages", []))


async def _hold(runtime, listing: dict, slot: str, replaces: dict | None = None) -> Command | str:
    """Create a pending visit and remember that we are waiting for the lead's yes."""
    repo, user_id = get_repo(), runtime.context.user_id
    try:
        when = parse_slot(slot)
    except ValueError:
        return "Invalid slot. Call check_slots and pass a slot id exactly, e.g. 2026-11-28T15:00."
    if when not in upcoming_slots() or when in await repo.booked_slots(listing["id"]):
        return "That slot is not available. Call check_slots for free slots."
    earlier = (runtime.state or {}).get("pending_action") or {}
    if earlier.get("visit_id"):                                  # a new hold replaces the previous unconfirmed one
        await repo.cancel_visit(user_id, earlier["visit_id"], only_pending=True)
    visit = await repo.create_visit(user_id, listing["id"], when)
    label = f"#{listing['id']} {listing['title']} ({listing['area']}) on {slot_label(when)}"
    summary = f"move your visit to {label}" if replaces else f"book a visit to {label}"
    return Command(update={
        "pending_action": {"tool": "confirm_visit", "args": {}, "summary": summary, "human_turn": human_turn(runtime),
                           "visit_id": visit["id"], "replaces": replaces["id"] if replaces else None},
        "messages": [ToolMessage(f"Held, not booked yet. Ask the lead: shall I {summary}? "
                                 "Do not call confirm_visit until they say yes.", tool_call_id=runtime.tool_call_id)],
    })


@tool
async def request_visit(listing_id: int, slot: str, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Hold a site-visit slot. slot is a slot id from check_slots, e.g. 2026-11-28T15:00.
    After this, ask the lead to confirm. Do NOT call confirm_visit until they say yes."""
    listing = await get_repo().get_listing(listing_id)
    return await _hold(runtime, listing, slot) if listing else f"No listing #{listing_id}."


@tool
async def reschedule_visit(visit_id: int, slot: str, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Move one of the lead's booked visits to a new slot. Holds the new slot; the old one is kept until they say yes."""
    repo = get_repo()
    visit = await repo.get_visit(runtime.context.user_id, visit_id)
    if not visit or visit["status"] != "confirmed":
        return f"This lead has no booked visit #{visit_id}. Call my_visits."
    return await _hold(runtime, await repo.get_listing(visit["listing_id"]), slot, replaces=visit)


@tool
async def confirm_visit(runtime: ToolRuntime[Ctx]) -> Command | str:
    """Book the held visit. Only call this after the lead clearly says yes to it."""
    pending = (runtime.state or {}).get("pending_action") or {}
    if not pending.get("visit_id"):
        return "There is no held visit to confirm. Use check_slots and request_visit first."
    repo, user_id = get_repo(), runtime.context.user_id
    visit = await repo.confirm_visit(user_id, pending["visit_id"])
    if not visit:
        text = "That slot was just taken. Nothing was booked. Offer the lead other slots."
    else:
        if pending.get("replaces"):
            await repo.cancel_visit(user_id, pending["replaces"])
        text = f"Done: {pending['summary']} (visit #{visit['id']} is confirmed)."
    return Command(update={"pending_action": None,
                           "messages": [ToolMessage(text, tool_call_id=runtime.tool_call_id)]})


@tool
async def cancel_visit(visit_id: int, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Cancel one of the lead's own visits. The lead is asked to confirm first."""
    visit = await get_repo().cancel_visit(runtime.context.user_id, visit_id)
    text = f"Visit #{visit_id} is cancelled." if visit else f"This lead has no active visit #{visit_id}. Call my_visits."
    return Command(update={"pending_action": None,
                           "messages": [ToolMessage(text, tool_call_id=runtime.tool_call_id)]})


@tool
async def my_visits(runtime: ToolRuntime[Ctx]) -> str:
    """List this lead's own site visits with their ids and status."""
    visits = await get_repo().user_visits(runtime.context.user_id)
    if not visits:
        return "This lead has no visits yet."
    return "\n".join(f"Visit #{v['id']}: {visit_label(v)} — {v['status']}" for v in visits)


@tool
async def schedule_followup(message: str, runtime: ToolRuntime[Ctx], due_in_days: int = 2) -> str:
    """Queue a follow-up message to this lead. It is NOT sent: the agency approves it on the dashboard first."""
    due = now_pkt() + timedelta(days=max(1, min(due_in_days, 30)))
    item = await get_repo().add_followup(runtime.context.user_id, redact(message)[:500], due)
    return f"Follow-up #{item['id']} queued for agency approval (due {due:%d %b}). It has not been sent."


TOOLS = [search_listings, get_listing, check_slots, calculate_installment, save_lead_profile, my_data, forget_me,
         request_visit, reschedule_visit, confirm_visit, cancel_visit, my_visits, schedule_followup]
