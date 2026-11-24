"""Token economics: what every turn costs, and a hard stop before the $2 key is empty.

/chat is open to the internet (the grader needs that), so a stranger's script could burn the key. Two caps:
  hourly  limits how fast money can leave; a full benchmark run stays far below it
  total   keeps a reserve so the key never dies mid-evaluation
When a cap is hit the API stays up and answers politely; it just stops calling the model.
"""
import logging
import time
from collections import deque

from app import config

log = logging.getLogger("dastak")

# claude-haiku-5-5, prompts up to 100K tokens, USD per million tokens
PRICE_INPUT, PRICE_OUTPUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 0.10, 0.50, 0.01, 0.125


def usage_parts(usage: dict) -> tuple[int, int, int, int]:
    """(uncached input, cache read, cache write, output). LangChain's input_tokens already includes cached tokens."""
    details = usage.get("input_token_details") or {}
    read = details.get("cache_read") or 0
    write = (details.get("cache_creation") or 0) + (details.get("ephemeral_5m_input_tokens") or 0) \
        + (details.get("ephemeral_1h_input_tokens") or 0)
    return max(0, usage.get("input_tokens", 0) - read - write), read, write, usage.get("output_tokens", 0)


def cost_usd(usage: dict) -> float:
    plain, read, write, out = usage_parts(usage)
    return (plain * PRICE_INPUT + read * PRICE_CACHE_READ + write * PRICE_CACHE_WRITE + out * PRICE_OUTPUT) / 1e6


class SpendMeter:
    clock = staticmethod(time.time)

    def __init__(self, total_cap: float, hourly_cap: float, already_spent: float = 0.0):
        self.total_cap, self.hourly_cap, self.total = total_cap, hourly_cap, already_spent
        self.calls = self.input = self.cache_read = self.cache_write = self.output = 0
        self._recent: deque[tuple[float, float]] = deque()

    def last_hour(self, now: float | None = None) -> float:
        cutoff = (now or self.clock()) - 3600
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
        return sum(usd for _, usd in self._recent)

    def allow(self, now: float | None = None) -> bool:
        return self.total < self.total_cap and self.last_hour(now) < self.hourly_cap

    def record(self, usage: dict) -> float:
        plain, read, write, out = usage_parts(usage)
        usd = cost_usd(usage)
        self.calls, self.input, self.output = self.calls + 1, self.input + plain, self.output + out
        self.cache_read, self.cache_write = self.cache_read + read, self.cache_write + write
        self.total += usd
        self._recent.append((self.clock(), usd))
        return usd

    def report(self) -> dict:
        seen = self.input + self.cache_read + self.cache_write
        return {"total_usd": round(self.total, 6), "last_hour_usd": round(self.last_hour(), 6),
                "total_cap_usd": self.total_cap, "hourly_cap_usd": self.hourly_cap, "model_calls": self.calls,
                "cache_hit_rate": round(self.cache_read / seen, 3) if seen else None,
                "tokens": {"input": self.input, "cache_read": self.cache_read, "cache_write": self.cache_write,
                           "output": self.output}, "model_allowed": self.allow()}


METER = SpendMeter(config.MAX_SPEND_USD, config.MAX_USD_PER_HOUR)
