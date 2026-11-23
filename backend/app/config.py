"""All settings come from environment variables (see ../.env.example). Never hard-code keys."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env first, then the repo-root .env, so either location works locally.
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE.parent / ".env")
load_dotenv(_HERE.parent.parent / ".env")

MODEL = os.getenv("MODEL", "claude-haiku-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))          # cap per reply (cost efficiency)
HISTORY_MESSAGES = int(os.getenv("HISTORY_MESSAGES", "16"))  # short-term memory window sent to the model
REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "45"))

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()     # Neon Postgres; empty = in-memory dev mode
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
