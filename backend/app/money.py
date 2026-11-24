"""Understand money the way people in Pakistan say it: "dedh crore", "paune do crore", "80 lac", "85k", "2 crore 50 lakh".

Pure Python, so zeros are never lost in the model's arithmetic. Ambiguous amounts raise ValueError: LangGraph hands
that message to the model, which then asks the lead instead of guessing.
"""
import re

UNITS = {"crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "karor": 10_000_000, "karore": 10_000_000,
         "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "laakh": 100_000,
         "k": 1_000, "thousand": 1_000, "hazar": 1_000, "hazaar": 1_000,
         "million": 1_000_000, "mn": 1_000_000, "arab": 1_000_000_000, "billion": 1_000_000_000}
NUMBERS = {"ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4, "paanch": 5,
           "panch": 5, "five": 5, "chay": 6, "chhe": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9,
           "nine": 9, "das": 10, "ten": 10, "dedh": 1.5, "derh": 1.5, "dhai": 2.5, "dhaai": 2.5, "adhai": 2.5,
           "aadha": 0.5, "adha": 0.5, "half": 0.5}
SHIFT = {"paune": -0.25, "pone": -0.25, "sawa": 0.25, "sarhe": 0.5, "saarhe": 0.5, "sadhe": 0.5}
FILLER = {"pkr", "rs", "rupees", "rupay", "about", "around", "approx", "tak", "qareeb", "up", "to", "under", "max",
          "budget", "and", "aur", "a", "month", "per", "only"}


def _fail(value):
    raise ValueError(f"Unclear amount {value!r}. Ask the lead whether they mean lakh or crore.")


def parse_pkr(value) -> int:
    if isinstance(value, bool) or value is None:
        _fail(value)
    if isinstance(value, (int, float)):
        return int(value) if value >= 1000 else _fail(value)
    text = re.sub(r"(?<=\d),(?=\d)", "", str(value).lower())
    if re.search(r"\d\s*-\s*\d", text):                       # a range: "50-60 lakh"
        _fail(value)
    total, qty, shift, used_unit = 0.0, None, None, False
    for token in re.findall(r"\d+(?:\.\d+)?|[a-z]+", text):
        if token in UNITS:
            amount = 1 if qty is None else qty
            if shift is not None:
                amount += shift
            total, qty, shift, used_unit = total + amount * UNITS[token], None, None, True
        elif token in SHIFT and qty is None and shift is None:
            shift = SHIFT[token]
        elif token[0].isdigit() or token in NUMBERS:
            if qty is not None:                               # two numbers, no unit between: "1 to 2 crore"
                _fail(value)
            qty = float(token) if token[0].isdigit() else NUMBERS[token]
        elif token not in FILLER:
            _fail(value)
    if qty is not None:                                       # a number with no unit at the end
        if used_unit or shift is not None or qty < 1000:
            _fail(value)
        total = qty
    return round(total) if total >= 1000 else _fail(value)
