"""The agent's tools. Every tool reads the lead's identity from runtime.context (set by the API),
never from a model argument, so one lead can never read or write another lead's data.

Long-term memory lives in the LangGraph Store under ("leads", user_id) -> "profile".
Tools that change the graph's state return a Command (same pattern as the instructor's verify_identity).
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import timedelta
from typing import Annotated, Literal, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BeforeValidator

from app.context import Ctx
from app.guard import check_message
from app.ids import memory_namespace
from app.money import parse_pkr
from app.privacy import redact
from app.repo import PKT, format_pkr, get_repo, listing_line, now_pkt, search, slot_label, upcoming_slots
from app.when import parse_when

log = logging.getLogger("propcloser")
PROFILE_KEY = "profile"
RISKY_TOOLS = {"confirm_visit", "cancel_visit", "forget_me"}      # must pass the approval_gate node
MAX_NOTES = 8
LIMITS = {"name": 60, "area": 60, "timeline": 80, "financing": 80, "note": 160}      # memory is paid on every call

# The model sees a plain integer; people's words ("dedh crore") are still understood if it passes them through.
Pkr = Annotated[int, BeforeValidator(parse_pkr)]

_profile_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


def profile_lock(user_id: str) -> asyncio.Lock:
    """Two saves in one message run at the same time; this stops them overwriting each other."""
    key = (id(asyncio.get_running_loop()), user_id)
    lock = _profile_locks.get(key)
    if lock is None:
        lock = _profile_locks[key] = asyncio.Lock()
    return lock


def clean_fact(field: str, value: str) -> str:
    """One short line, no private identifiers, and never an instruction (this text is shown to the model later)."""
    text = " ".join(redact(str(value)).split())[:LIMITS[field]]
    return "" if check_message(text) else text


async def free_slots(listing_id: int):
    taken = await get_repo().booked_slots(listing_id)
    return [s for s in upcoming_slots() if s not in taken]


def slots_text(slots) -> str:
    """Compact: one line per day. (Full ids per slot cost 3x the tokens.)"""
    days: dict[str, list[str]] = {}
    for s in slots:
        local = s.astimezone(PKT)
        days.setdefault(f"{local:%a %d %b}", []).append(f"{local:%H:%M}")
    return "; ".join(f"{day} {', '.join(times)}" for day, times in days.items()) or "none in the next 7 days"


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
    """Search the agency's Islamabad listings. max_price_pkr in full rupees (1 crore = 10000000); monthly if rent."""
    rows, exact = search(await get_repo().all_listings(), purpose, area, property_type, min_beds, max_price_pkr)
    if not rows:
        return "No listings found."
    head = "Matching listings:" if exact else "No exact match. Closest options:"
    return head + "\n" + "\n".join(listing_line(r) for r in rows)


@tool
async def get_listing(listing_id: int) -> str:
    """Full details of one listing id."""
    listing = await get_repo().get_listing(listing_id)
    if not listing:
        return f"No listing #{listing_id}."
    return f"{listing_line(listing)}\nSector: {listing.get('sector') or '-'}\n{listing.get('description') or ''}"


@tool
async def check_slots(listing_id: int) -> str:
    """Free visit times for a listing. Only needed when the lead asks which times are free."""
    if not await get_repo().get_listing(listing_id):
        return f"No listing #{listing_id}."
    return f"Free times for #{listing_id}: {slots_text(await free_slots(listing_id))}"


@tool
def calculate_installment(price_pkr: Pkr, down_payment_pct: float = 20, years: int = 10,
                          annual_rate_pct: float = 12) -> str:
    """Estimated monthly installment for a purchase price."""
    if years <= 0 or not 0 <= down_payment_pct < 100:
        return "Please give a down payment between 0 and 99%, and at least 1 year."
    loan = price_pkr * (1 - down_payment_pct / 100)
    r, n = annual_rate_pct / 100 / 12, years * 12
    monthly = loan * r / (1 - (1 + r) ** -n) if r else loan / n
    return (f"Down payment PKR {format_pkr(price_pkr - loan)}, financed PKR {format_pkr(loan)}. "
            f"Monthly installment ≈ PKR {monthly:,.0f} for {years} years at {annual_rate_pct:g}% (estimate).")


def done(runtime, key: str, what: str, text: str) -> Command:
    """Finish a confirmed action. The artifact lets the graph reply from a template instead of paying for a model call."""
    return Command(update={"pending_action": None, "messages": [ToolMessage(
        text, artifact={"reply": key, "what": what}, tool_call_id=runtime.tool_call_id)]})


# ── long-term memory ──

@tool
async def save_lead_profile(runtime: ToolRuntime[Ctx], name: Optional[str] = None, budget_pkr: Optional[Pkr] = None,
                            area: Optional[str] = None, purpose: Optional[Literal["sale", "rent"]] = None,
                            property_type: Optional[Literal["house", "flat", "plot"]] = None,
                            beds: Optional[int] = None, timeline: Optional[str] = None,
                            financing: Optional[str] = None, note: Optional[str] = None) -> str:
    """Save facts the lead said about themselves. note: one other lasting fact, e.g. 'needs parking for 2 cars'.
    Never phone numbers, CNIC or payment details."""
    given = {"name": name, "budget_pkr": budget_pkr, "area": area, "purpose": purpose,
             "property_type": property_type, "beds": beds, "timeline": timeline, "financing": financing}
    fields = {k: clean_fact(k, v) if k in LIMITS else v for k, v in given.items() if v not in (None, "")}
    fields = {k: v for k, v in fields.items() if v != ""}
    note = clean_fact("note", note) if note else ""
    user_id = runtime.context.user_id
    async with profile_lock(user_id):
        profile = {**await read_profile(runtime.store, user_id), **fields}
        if note:
            profile["notes"] = ([n for n in profile.get("notes", []) if n != note] + [note])[-MAX_NOTES:]
        await runtime.store.aput(memory_namespace(user_id), PROFILE_KEY, profile)
        await get_repo().upsert_lead(user_id, fields)
    return "Saved " + (", ".join([*fields, *(["note"] if note else [])]) or "nothing new") + "."


@tool
async def my_data(runtime: ToolRuntime[Ctx]) -> str:
    """Everything remembered about this lead, when they ask what you know about them."""
    memory = await full_memory(runtime.store, runtime.context.user_id)
    return "\n".join(f"- {k.replace('_', ' ')}: {'; '.join(v) if isinstance(v, list) else v}"
                     for k, v in memory.items()) or "Nothing is saved about this lead."


@tool
async def forget_me(runtime: ToolRuntime[Ctx]) -> Command:
    """Delete everything remembered about the lead, only when they ask for that. To change one fact use save_lead_profile."""
    user_id = runtime.context.user_id
    async with profile_lock(user_id):
        await runtime.store.adelete(memory_namespace(user_id), PROFILE_KEY)
        await get_repo().delete_lead(user_id)
    return done(runtime, "forgotten", "", "Deleted.")          # the API also erases this lead's chats (service.py)


# ── visits (human approval required) ──

def human_turn(runtime) -> int:
    return sum(isinstance(m, HumanMessage) for m in (runtime.state or {}).get("messages", []))


async def _hold(runtime, listing: dict, said: str, replaces: dict | None = None) -> Command | str:
    """Create a pending visit and remember that we are waiting for the lead's yes."""
    repo, user_id = get_repo(), runtime.context.user_id
    free = await free_slots(listing["id"])
    when = parse_when(said, free, now_pkt())
    if not when:
        return f"No free time matches {said!r}. Nothing held. Free times: {slots_text(free)}"
    earlier = (runtime.state or {}).get("pending_action") or {}
    if earlier.get("visit_id"):                                  # a new hold replaces the previous unconfirmed one
        await repo.cancel_visit(user_id, earlier["visit_id"], only_pending=True)
    visit = await repo.create_visit(user_id, listing["id"], when)
    label = f"#{listing['id']} {listing['title']} ({listing['area']}) on {slot_label(when)}"
    summary = f"move your visit to {label}" if replaces else f"book a visit to {label}"
    return Command(update={
        "pending_action": {"tool": "confirm_visit", "args": {}, "summary": summary, "what": label,
                           "human_turn": human_turn(runtime),
                           "visit_id": visit["id"], "replaces": replaces["id"] if replaces else None},
        "messages": [ToolMessage(f"Held, not booked yet. Ask the lead: shall I {summary}?",
                                 tool_call_id=runtime.tool_call_id)],
    })


@tool
async def request_visit(listing_id: int, runtime: ToolRuntime[Ctx], when: str = "earliest") -> Command | str:
    """Hold a visit time, then ask the lead to confirm it. when: their words, e.g. 'earliest', 'saturday 3pm', 'kal'."""
    listing = await get_repo().get_listing(listing_id)
    return await _hold(runtime, listing, when) if listing else f"No listing #{listing_id}."


@tool
async def reschedule_visit(visit_id: int, when: str, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Hold a new time for a booked visit, then ask the lead to confirm. The old time is kept until they say yes."""
    repo = get_repo()
    visit = await repo.get_visit(runtime.context.user_id, visit_id)
    if not visit or visit["status"] != "confirmed":
        return f"This lead has no booked visit #{visit_id}. Call my_visits."
    return await _hold(runtime, await repo.get_listing(visit["listing_id"]), when, replaces=visit)


@tool
async def confirm_visit(runtime: ToolRuntime[Ctx]) -> Command | str:
    """Book the held visit, only after the lead clearly said yes to it."""
    pending = (runtime.state or {}).get("pending_action") or {}
    if not pending.get("visit_id"):
        return "There is no held visit to confirm. Use request_visit first."
    repo, user_id = get_repo(), runtime.context.user_id
    visit = await repo.confirm_visit(user_id, pending["visit_id"], replaces=pending.get("replaces"))
    if not visit:
        held = await repo.get_visit(user_id, pending["visit_id"])
        free = slots_text((await free_slots(held["listing_id"]))[:6]) if held else "-"
        return done(runtime, "taken", free, f"That slot was just taken. Nothing was booked. Free times: {free}")
    return done(runtime, "moved" if pending.get("replaces") else "booked", pending["what"],
                f"Booked: {pending['what']} (visit #{visit['id']}).")


@tool
async def cancel_visit(visit_id: int, runtime: ToolRuntime[Ctx]) -> Command | str:
    """Cancel one of the lead's visits. The lead is asked to confirm first."""
    repo, user_id = get_repo(), runtime.context.user_id
    if not await repo.cancel_visit(user_id, visit_id):
        return done(runtime, "gone", "", f"This lead has no active visit #{visit_id}. Call my_visits.")
    visit = await repo.get_visit(user_id, visit_id)
    return done(runtime, "cancelled", visit_label(visit), f"Cancelled: {visit_label(visit)}.")


@tool
async def my_visits(runtime: ToolRuntime[Ctx]) -> str:
    """This lead's own visits with ids and status."""
    visits = await get_repo().user_visits(runtime.context.user_id)
    if not visits:
        return "This lead has no visits yet."
    return "\n".join(f"Visit #{v['id']}: {visit_label(v)} — {v['status']}" for v in visits)


@tool
async def schedule_followup(message: str, runtime: ToolRuntime[Ctx], due_in_days: int = 2) -> str:
    """Queue a follow-up message for the agency to approve. It is not sent."""
    due = now_pkt() + timedelta(days=max(1, min(due_in_days, 30)))
    item = await get_repo().add_followup(runtime.context.user_id, redact(message)[:500], due)
    return f"Follow-up #{item['id']} queued for agency approval (due {due:%d %b}). It has not been sent."


def tool_error(error: Exception) -> str:
    """Wrong arguments go back to the model so it can fix them; anything else is logged, never shown."""
    if type(error).__name__ in ("ToolInvocationError", "ValidationError", "ValueError"):
        return f"Invalid arguments: {str(error)[:300]}"
    log.error("TOOL FAILED %s: %s", type(error).__name__, error, exc_info=error)
    return "This action is temporarily unavailable. Apologise and suggest trying again in a minute."


def compact(schema: dict) -> dict:
    """Same schema, a third fewer tokens: drops titles, null defaults and 'anyOf ... null' noise."""
    props = {}
    for name, p in schema.get("properties", {}).items():
        p = next((o for o in p["anyOf"] if o.get("type") != "null"), p) if "anyOf" in p else dict(p)
        props[name] = {k: v for k, v in p.items() if k not in ("title",) and not (k == "default" and v is None)}
    out = {"type": "object", "properties": props}
    return {**out, "required": schema["required"]} if schema.get("required") else out


TOOLS = [search_listings, get_listing, check_slots, calculate_installment, save_lead_profile, my_data, forget_me,
         request_visit, reschedule_visit, confirm_visit, cancel_visit, my_visits, schedule_followup]

# What the model sees. ToolNode still validates every call against the full Python signature.
TOOL_SPECS = [{"name": t.name, "description": t.description, "input_schema": compact(t.tool_call_schema.model_json_schema())}
              for t in TOOLS]
