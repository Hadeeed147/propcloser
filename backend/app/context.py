"""Per-request context. Set by the API from the request body, never by the model."""
from dataclasses import dataclass


@dataclass
class Ctx:
    user_id: str
