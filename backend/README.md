---
title: PropCloser API
emoji: 🏠
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# PropCloser agent API

FastAPI + LangGraph backend for PropCloser (Track 3: DealCloser). The header above is the
Hugging Face Spaces config: this folder is pushed as-is to the Space.

- `POST /chat` — `{"user_id", "thread_id", "message"}` → `{"reply", "tool_calls", "tokens": {"in", "out"}}`
- `GET /health` — `ok`; `GET /ready` — is the key, database and budget fine?
- `GET /docs` — interactive API docs

Secrets to set on the Space: `ANTHROPIC_API_KEY`, `DATABASE_URL`, `ADMIN_TOKEN`.
See the main repository README for the full project.
