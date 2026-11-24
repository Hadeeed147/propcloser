"""Understand visit times the way people say them: "earliest", "saturday 3pm", "kal 3 baje", "jumma shaam".

One tool call instead of three (list slots, pick, hold), and the calendar arithmetic is never done by the model.
Returns the first FREE slot that fits, or None. The lead still confirms the exact time before anything is booked.
"""
import re
from datetime import datetime, timedelta

DAYS = {0: ("monday", "mon", "peer", "somwar"), 1: ("tuesday", "tue", "tues", "mangal"), 2: ("wednesday", "wed", "budh"),
        3: ("thursday", "thu", "thurs", "jumerat", "jumeraat"), 4: ("friday", "fri", "juma", "jumma"),
        5: ("saturday", "sat", "hafta", "hafte"), 6: ("sunday", "sun", "itwar", "itwaar")}
WEEKDAY = {name: day for day, names in DAYS.items() for name in names}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
ANY = re.compile(r"\b(earliest|first|soonest|asap|any ?time|any|next (free|available)|jaldi|pehla|sab se pehle)\b")
PART = {"morning": {11}, "subah": {11}, "afternoon": {15}, "dopahar": {15}, "dopeher": {15}, "evening": {17}, "shaam": {17},
        "sham": {17}}


def parse_when(text: str, free: list[datetime], now: datetime) -> datetime | None:
    text = (text or "").lower().strip()
    exact = re.match(r"(\d{4})-(\d{2})-(\d{2})[t ](\d{2}):(\d{2})", text)
    if exact:
        want = datetime(*map(int, exact.groups()), tzinfo=now.tzinfo)
        return want if want in free else None

    day = hours = None
    words = re.findall(r"[a-z]+", text)
    date = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(" + "|".join(MONTHS) + r")", text) or \
        re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\s*(\d{1,2})\b", text)
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso:
        day = datetime(*map(int, iso.groups())).date()
    elif date:
        a, b = date.groups()
        num, month = (int(a), b) if a.isdigit() else (int(b), a)
        match = [s.date() for s in free if s.day == num and s.month == MONTHS[month[:3]]]
        if not match:
            return None
        day = match[0]
        text = text.replace(date.group(0), " ")
    elif "tomorrow" in words or "kal" in words:
        day = (now + timedelta(days=1)).date()
    elif "today" in words or "aaj" in words:
        day = now.date()
    weekday = next((WEEKDAY[w] for w in words if w in WEEKDAY), None) if day is None else None

    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?\b", text if not iso else text.replace(iso.group(0), " "))
    if clock:
        hour, half = int(clock.group(1)), clock.group(3)
        if half == "pm" and hour < 12:
            hour += 12
        elif half == "baje" and hour < 9:                      # "3 baje" for a visit means the afternoon
            hour += 12
        elif half is None and not clock.group(2) and hour < 9:
            hour += 12
        hours = {hour} if clock.group(2) in (None, "00") else set()
    else:
        hours = next((PART[w] for w in words if w in PART), None)

    if day is None and weekday is None and hours is None:
        return free[0] if free and ANY.search(text) else None
    return next((s for s in free if (day is None or s.date() == day) and (weekday is None or s.weekday() == weekday)
                 and (hours is None or s.hour in hours)), None)
