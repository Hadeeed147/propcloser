"""Rules-based safety checks for the `guard` node. No LLM call, so blocked messages cost 0 tokens.

The closer prompt also refuses anything off-topic these rules miss; this layer catches the
obvious attacks deterministically so they can never reach the model or the tools.
Keep the patterns narrow: a false positive refuses a real buyer.
"""
import re

MAX_CHARS = 2000

INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules|prompts?|guidelines|polic(y|ies))\b"
    r"|\b(reveal|show|print|repeat|leak|output|tell me|what is|what are|give me)\b.{0,30}"
    r"\b(system|hidden|initial|secret|developer)\s+(prompt|instructions?|message|rules)\b"
    r"|\b(repeat|print|output|copy)\b.{0,25}\b(everything|all( the)? text|your instructions)\b.{0,25}\b(above|before|earlier)\b"
    r"|\bsystem prompt\b|\bjailbreak|\bdeveloper mode\b|\bprompt injection\b|\bunrestricted (ai|mode|assistant)\b"
    r"|\b(you are now|from now on you are|pretend (to be|you are)|act as (if|though)|roleplay as)\b"
    r"|\bnew instructions?\s*:"
    r"|\b(drop|truncate)\s+table\b|\bselect\s+\*\s+from\b"
    r"|\b(api[_ ]?key|anthropic[_ ]?key|database url|env(ironment)? variables?)\b",
    re.I | re.S,
)

EXFILTRATION = re.compile(
    r"\b(list|show|give|export|dump|send|share)\b.{0,15}\b(all|every|other|another)\b.{0,15}"
    r"\b(users?|leads?|customers?|clients?|buyers?)\b"
    r"|\b(all|every|other|another)\s+(users?|leads?|customers?|clients?|buyers?)('s|s')?\b.{0,25}"
    r"\b(phone|numbers?|emails?|cnic|data|details|info|bookings?|visits?|budgets?|names?|contacts?)\b"
    r"|\b(previous|last|other|another)\s+(customer|user|client|lead|buyer)s?\b.{0,40}"
    r"\b(ask|said|want|budget|phone|number|email|details|data|book|visit)"
    r"|\bsomeone else'?s\b|\buser[_ ]?id\b|\bthread[_ ]?id\b",
    re.I | re.S,
)

OFF_TOPIC = re.compile(
    r"\b(write|compose|generate|tell)\b.{0,20}\b(poem|song|lyrics|story|essay|joke|code|program|script|tweet)\b"
    r"|\b(poem|lyrics|recipe|homework|assignment|essay)\b"
    r"|\b(python|javascript|c\+\+|sql query|leetcode)\b"
    r"|\b(translate|capital of|who won|world cup|cricket score|horoscope|bitcoin|stock price)\b"
    r"|\b(politics|political|election|religion|religious|prime minister)\b"
    r"|\b(diagnose|diagnosis|symptoms?|prescription)\b",
    re.I | re.S,
)

REFUSALS = {
    "injection": ("I can't do that. I'm PropCloser, this agency's property assistant, and I only help with "
                  "buying or renting property in Islamabad. What kind of home are you looking for?"),
    "exfiltration": ("I can't share anything about other clients or our systems — every client's details are "
                     "private. I'm happy to help with your own property search, though. What are you looking for?"),
    "off_topic": ("That's outside what I can help with — I'm PropCloser, and I only help with buying or renting "
                  "property in Islamabad (listings, prices, installments and site visits). What are you looking for?"),
    "too_long": "That message is too long for me. Could you tell me in a few lines what property you're looking for?",
}


def check_message(text: str) -> str | None:
    """Return a block reason, or None if the message may go to the agent."""
    text = text or ""
    if len(text) > MAX_CHARS:
        return "too_long"
    if INJECTION.search(text):
        return "injection"
    if EXFILTRATION.search(text):
        return "exfiltration"
    if OFF_TOPIC.search(text):
        return "off_topic"
    return None


def refusal_for(reason: str | None) -> str:
    return REFUSALS.get(reason or "", REFUSALS["off_topic"])
