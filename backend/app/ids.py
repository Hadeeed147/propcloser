"""Turn any client-sent id into a safe storage key. Two different ids can never become the same key.

LangGraph's Store rejects "." in a namespace (so a raw e-mail as user_id would break every turn), and joining raw ids
with ":" would let user "a:b" + thread "c" collide with user "a" + thread "b:c".
"""
from urllib.parse import quote


def safe_id(raw: str) -> str:
    return quote(raw, safe="").replace(".", "%2E")


def thread_key(user_id: str, thread_id: str) -> str:
    """Checkpointer key. Includes user_id, so two users sending the same thread_id never share a chat."""
    return f"{safe_id(user_id)}:{safe_id(thread_id)}"


def memory_namespace(user_id: str) -> tuple[str, str]:
    return ("leads", safe_id(user_id))
