"""All settings come from environment variables (see ../.env.example). Never hard-code keys."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env first, then the repo-root .env, so either location works locally.
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE.parent / ".env")
load_dotenv(_HERE.parent.parent / ".env")

MODEL = os.getenv("MODEL", "claude-haiku-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))             # backstop only; length is set by the prompt
EFFORT = os.getenv("EFFORT", "low")                          # low | medium | high (thinking is off, see graph.make_model)
HISTORY_MESSAGES = int(os.getenv("HISTORY_MESSAGES", "40"))  # short-term memory window sent to the model
MAX_MODEL_CALLS = int(os.getenv("MAX_MODEL_CALLS", "5"))     # per turn; a looping model cannot burn the key

# Timeouts nest: one model call (15 s, one retry) fits inside one request (45 s)
MODEL_TIMEOUT_S = float(os.getenv("MODEL_TIMEOUT_S", "15"))
MODEL_RETRIES = int(os.getenv("MODEL_RETRIES", "1"))
REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "45"))
MAX_CONCURRENT_TURNS = int(os.getenv("MAX_CONCURRENT_TURNS", "8"))

# Agents available per listing per visit time. With 1, test users would block each other's bookings.
SLOT_CAPACITY = int(os.getenv("SLOT_CAPACITY", "4"))

# Money (app/budget.py). The key stops at $2; keep a margin for calls made outside this server.
MAX_SPEND_USD = float(os.getenv("MAX_SPEND_USD", "1.80"))
MAX_USD_PER_HOUR = float(os.getenv("MAX_USD_PER_HOUR", "0.40"))

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()         # Neon Postgres; empty = in-memory dev mode
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
