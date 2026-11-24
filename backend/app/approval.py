"""What counts as a human "yes". Two strengths, on purpose:

is_exact_yes  the WHOLE message is a yes ("haan ji", "ok confirm"). Safe enough to act on without asking the model.
is_yes        the message contains a yes and nothing that takes it back. Used when the model itself asks to act.
"""
import re

YES_WORDS = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "confirm", "confirmed", "haan", "han", "jee", "ji",
             "bilkul", "theek", "thik"}
YES_PHRASES = ("go ahead", "book it", "kar do", "kardo", "kar den")
FILLER = {"please", "plz", "pls", "thanks", "thank", "you", "it", "that", "hai", "sir", "shukriya", "book", "go", "ahead",
          "kar", "do", "den", "kardo", "the", "visit"}

TAKES_IT_BACK = re.compile(r"^\s*(no|nope|nahi|nahin)\b|\b(not now|don'?t|do not|nahi|nahin|mat karo|wait|ruk|but|lekin|"
                           r"magar|instead)\b", re.I)


def is_exact_yes(text: str) -> bool:
    text = (text or "").lower().strip()
    if not text or "?" in text:
        return False
    words = re.findall(r"[a-z']+", text)
    if not words or len(words) > 6 or re.search(r"\d", text):
        return False
    says_yes = any(w in YES_WORDS for w in words) or any(p in " ".join(words) for p in YES_PHRASES)
    return says_yes and all(w in YES_WORDS or w in FILLER for w in words)


def is_yes(text: str, tool: str) -> bool:
    text = (text or "").lower()
    if TAKES_IT_BACK.search(text) or (tool != "cancel_visit" and re.search(r"\bcancel\b", text)):
        return False
    return any(w in YES_WORDS for w in re.findall(r"[a-z']+", text)) or any(p in text for p in YES_PHRASES)
