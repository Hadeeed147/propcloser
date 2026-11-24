"""A strict local stand-in for api.anthropic.com. The REAL Claude client talks to it over HTTP.

It rejects what claude-haiku-5-5 rejects (sampling parameters, unanswered tool calls, empty text, bad roles...) and it
simulates the prompt cache, so tests can assert what a conversation costs. Token counts are estimates (3.2 characters per
token); `check_model.py` measures the real ones.
"""
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHARS_PER_TOKEN, CACHE_MINIMUM_TOKENS = 3.2, 512


def blocks_of(message):
    c = message["content"]
    return [{"type": "text", "text": c}] if isinstance(c, str) else c


def problems(r):
    out = [f"sampling parameter {k}" for k in ("temperature", "top_p", "top_k") if k in r]
    if r.get("model") != "claude-haiku-5-5":
        out.append(f"model {r.get('model')}")
    if r.get("thinking") != {"type": "disabled"}:
        out.append(f"thinking {r.get('thinking')}")
    msgs = r["messages"]
    if msgs[0]["role"] != "user" or msgs[-1]["role"] != "user":
        out.append("conversation must start and end with the user")
    if any(a["role"] == b["role"] for a, b in zip(msgs, msgs[1:])):
        out.append("two messages in a row with the same role")
    marks = sum("cache_control" in b for b in [*r["system"], *[b for m in msgs for b in blocks_of(m)]])
    if marks > 4:
        out.append("more than 4 cache breakpoints")
    for i, m in enumerate(msgs):
        blocks = blocks_of(m)
        for b in blocks:
            if b["type"] == "text" and not b["text"].strip():
                out.append(f"empty text block in message {i}")
            if b["type"] == "tool_use" and not re.fullmatch(r"[a-zA-Z0-9_-]+", b["id"]):
                out.append("bad tool id")
        if m["role"] == "assistant":
            asked = {b["id"] for b in blocks if b["type"] == "tool_use"}
            nxt = blocks_of(msgs[i + 1]) if i + 1 < len(msgs) else []
            got = {b["tool_use_id"] for b in nxt if b["type"] == "tool_result"}
            if asked != got:
                out.append(f"unanswered tool calls {asked ^ got}")
            if asked and nxt and nxt[0]["type"] != "tool_result":
                out.append("tool results must come first in the next message")
    return out


class StrictClaude:
    """brain(request) -> list of content blocks to answer with."""

    def __init__(self, brain):
        self.brain, self.requests, self.errors, self.cache, self.usage = brain, [], [], set(), []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                code, body = outer.answer(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def _meter(self, r, content):
        parts = [(json.dumps(t, sort_keys=True), False) for t in r["tools"]]
        parts += [(b["text"], "cache_control" in b) for b in r["system"]]
        for m in r["messages"]:
            for b in blocks_of(m):
                clean = {k: v for k, v in b.items() if k != "cache_control"}
                parts.append((m["role"] + json.dumps(clean, sort_keys=True), "cache_control" in b))
        prefix, size, trail, marks = "", 0.0, [], []
        for text, marked in parts:
            prefix, size = prefix + "\x1f" + text, size + len(text) / CHARS_PER_TOKEN
            trail.append((hash(prefix), size))
            if marked and size >= CACHE_MINIMUM_TOKENS:
                marks.append(len(trail) - 1)
        # Like the real API: from each breakpoint, look back up to 20 blocks for a prefix that is already cached.
        read = max((trail[i][1] for m in marks for i in range(max(0, m - 20), m + 1) if trail[i][0] in self.cache), default=0.0)
        last = max((trail[m][1] for m in marks), default=0.0)
        self.cache.update(trail[m][0] for m in marks)
        out = len(json.dumps(content)) / CHARS_PER_TOKEN
        return {"input_tokens": round(size - max(read, last)), "cache_read_input_tokens": round(read),
                "cache_creation_input_tokens": round(max(0.0, last - read)), "output_tokens": round(out)}

    def answer(self, r):
        with self._lock:
            self.requests.append(r)
            bad = problems(r)
            if bad:
                self.errors += bad
                return 400, {"type": "error", "error": {"type": "invalid_request_error", "message": "; ".join(bad)}}
            content = self.brain(r)
            usage = self._meter(r, content)
            self.usage.append(usage)
        return 200, {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant", "model": r["model"],
                     "content": content, "stop_sequence": None, "usage": usage,
                     "stop_reason": "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"}

    def cost_usd(self):
        return sum(u["input_tokens"] * 0.10 + u["cache_read_input_tokens"] * 0.01 + u["cache_creation_input_tokens"] * 0.125
                   + u["output_tokens"] * 0.50 for u in self.usage) / 1e6


def tool(name, **args):
    return {"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:12], "name": name, "input": args}


def text(words):
    return {"type": "text", "text": words}


def brain(r):
    """A crude model: tool calls for known phrases, otherwise words. Realistic reply length for costs."""
    last = blocks_of(r["messages"][-1])
    if any(b["type"] == "tool_result" for b in last):
        results = " ".join(c["text"] for b in last if b["type"] == "tool_result" for c in b["content"])
        return [text("Here is what I found: " + results[:220])]
    said = last[0]["text"].lower()
    memory = last[-1]["text"]
    if "dedh crore" in said:
        return [text("Noting that."), tool("save_lead_profile", budget_pkr="dedh crore", area="B-17"),
                tool("save_lead_profile", beds=3, note="needs parking, call 0300-1234567"),
                tool("search_listings", area="B-17", max_price_pkr="dedh crore")]
    if "book" in said:
        return [text("Holding it."), tool("request_visit", listing_id=11, when="earliest"), tool("confirm_visit")]
    if "cancel" in said:
        return [tool("cancel_visit", visit_id=1)]
    if "forget me" in said:
        return [tool("forget_me")]
    if "my budget" in said:
        return [text("MEMORY " + memory)]
    return [text("Sure. Could you tell me your preferred area and when you would like to move in? I can check listings now.")]
