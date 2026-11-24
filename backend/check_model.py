"""First thing to run after adding the group key to backend/.env:   python check_model.py

Two real claude-haiku-5-5 calls (well under $0.001 together) with the exact settings and tools the agent uses. Shows the
raw error if a call fails (the chat API hides errors behind a friendly reply, this does not), and proves that the prompt
cache works: the second call must read the cached prefix.
"""
import os
import sys

from langchain_core.messages import HumanMessage

from app import config  # noqa: F401  (loads .env)
from app.budget import cost_usd, usage_parts
from app.graph import make_model
from app.prompts import request_messages
from app.tools import TOOL_SPECS

if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY is empty. Put the group key in backend/.env (never in chat, never in git).")

model = make_model().bind_tools(TOOL_SPECS)
for attempt, text in enumerate(("Salam! 3 bed house in B-17, budget dedh crore", "Salam! flat for rent in E-11"), 1):
    reply = model.invoke(request_messages([HumanMessage(text)], {}, None))
    plain, read, write, out = usage_parts(reply.usage_metadata)
    print(f"--- call {attempt}: {text}")
    print("text      :", reply.text or "(none)")
    print("tool calls:", [(c["name"], c["args"]) for c in reply.tool_calls])
    print(f"tokens    : uncached={plain} cache_read={read} cache_write={write} out={out}  cost=${cost_usd(reply.usage_metadata):.6f}")
if not read:
    sys.exit("PROBLEM: the second call did not read the prompt cache. Costs will be several times higher than planned.")
print("OK: model, tools and prompt cache all work.")
