"""First thing to run after adding the group key to backend/.env:   python check_model.py

Makes ONE real claude-haiku-5-5 call with the exact settings and tools the agent uses, and shows the raw
error if it fails (the chat API hides errors behind a friendly reply, this does not).
"""
from langchain_core.messages import HumanMessage

from app.graph import make_model
from app.prompts import system_message
from app.tools import TOOLS

reply = make_model().bind_tools(TOOLS).invoke(
    [system_message({}, None), HumanMessage("Salam! 3 bed house in Bahria Town, budget dedh crore")])
print("text      :", reply.text)
print("tool calls:", [(c["name"], c["args"]) for c in reply.tool_calls])
print("usage     :", reply.usage_metadata)
print("stop      :", reply.response_metadata.get("stop_reason"))
