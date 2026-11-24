"""Remove private identifiers before anything goes into long-term memory (same idea as the instructor's PIIMiddleware)."""
import re

PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("card", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b|\b\d{16}\b")),
    ("cnic", re.compile(r"\b\d{5}-\d{7}-\d\b|\b\d{13}\b")),
    ("phone", re.compile(r"(?:\+92|0092|\b92|\b0)[\s-]?3\d{2}[\s-]?\d{3}[\s-]?\d{4}\b")),
]


def redact(text: str) -> str:
    for name, pattern in PATTERNS:
        text = pattern.sub(f"[{name} removed]", text)
    return text
