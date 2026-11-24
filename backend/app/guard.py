"""Rules-based safety checks for the `guard` node. No LLM call, so blocked messages cost 0 tokens.

Only clear attacks and clear off-topic TASKS are blocked here. Single words are never enough ("I'm a Python developer",
"is there a religious centre nearby" are real buyers): a wrong refusal loses a sale, while anything these rules miss is
still refused by the closer's prompt, and the tools cannot reach another user's data no matter what is asked.
"""
import re

MAX_CHARS = 2000

INJECTION = re.compile(
    r"\b(ignore|disregard|override|bypass)\b.{0,40}\b(instructions?|prompts?|guidelines|polic(y|ies)|(your|the|all|any) rules)\b"
    r"|\bforget\b.{0,25}\b(instructions?|prompts?|guidelines|(your|the|all) rules)\b"
    r"|\b(reveal|show|print|repeat|leak|output|tell me|what is|what are|give me)\b.{0,30}"
    r"\b(system|hidden|initial|secret|developer)\s+(prompt|instructions?|message|rules)\b"
    r"|\b(repeat|print|output|copy)\b.{0,25}\b(everything|all( the)? text|your instructions)\b.{0,25}\b(above|before|earlier)\b"
    r"|\bsystem prompt\b|\bjailbreak|\bdeveloper mode\b|\bprompt injection\b|\bunrestricted (ai|mode|assistant)\b"
    r"|\b(you are now|from now on you are|pretend (to be|you are)|roleplay as)\b"
    r"|\bact as (a|an|if|though)\b.{0,30}\b(ai|assistant|bot|model|hacker|admin|developer|no rules|unrestricted)\b"
    r"|\bnew instructions?\s*:|<\s*/?\s*(system|lead_memory)\b"
    r"|\b(drop|truncate)\s+table\b|\bselect\s+\*\s+from\b"
    r"|\b(api[_ ]?key|anthropic[_ ]?key|database url|env(ironment)? variables?)\b",
    re.I | re.S,
)

_PEOPLE = r"(users?|leads?|customers?|clients?|buyers?)('s|s')?"
_PRIVATE = r"(phone|numbers?|emails?|cnic|personal|data|info|information|budgets?|names?|contacts?|address(es)?)"

EXFILTRATION = re.compile(
    rf"\b(list|export|dump|send|share|show|give)\b.{{0,20}}\b(all|every|the other|other|another)\b.{{0,15}}\b{_PEOPLE}\b(?!.{{0,20}}\b(liked?|prefer)\b)"
    rf"|\b(all|every|other|another|previous|last)\s+{_PEOPLE}\b.{{0,30}}\b{_PRIVATE}\b"
    rf"|\b(previous|last|other|another)\s+{_PEOPLE}\b.{{0,20}}\b(ask|asked|said|say|want|wanted)\b.{{0,40}}\b({_PRIVATE}|about)\b"
    r"|\b(user|thread)_id\b",
    re.I | re.S,
)

OFF_TOPIC = re.compile(
    r"\b(write|compose|generate|tell|sing)\b.{0,20}\b(poem|song|lyrics|story|essay|joke|code|program|script|tweet)\b"
    r"|\b(write|solve|finish|do my|help me with)\b.{0,25}\b(homework|assignment|essay|exam|leetcode)\b"
    r"|\b(recipe for|capital of|who won|cricket score|horoscope|bitcoin price|stock price)\b"
    r"|\b(diagnose me|diagnose my|prescribe)\b",
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
