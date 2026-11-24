# Handoff: the agent core is ready to build on

You do not need to read the agent code. This page is the contract.

## Frozen API

```
POST /chat   {"user_id": "u1", "thread_id": "t1", "message": "..."}
          -> {"reply": "...", "tool_calls": [{"name": "...", "args": {...}}], "tokens": {"in": 0, "out": 0}}
GET  /health -> ok
```

- `tool_calls` lists only tools that really ran. A tool the approval gate stopped is not listed.
- Malformed JSON gets a 422 in the same shape. `/chat` never returns a 500.
- A reply starting with **"Sorry, I hit a problem"** means the model call failed. The real cause is in the API log on a
  line starting `CHAT FAILED`. The benchmark counts it as a fail.

Admin routes (header `X-Admin-Token`): `GET /admin/stats|leads|visits|followups`, `POST /admin/followups/{id}`
with `{"status": "approved"|"rejected"}`, and new: `POST /admin/sweep?idle_hours=24` -> `{"drafted": [...]}`.

## Environment variables

`ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon **direct** URL), `ADMIN_TOKEN`; optional `MODEL`, `MAX_TOKENS` (700),
`EFFORT` (low), `HISTORY_MESSAGES` (40). If you copied an old `.env` with `MAX_TOKENS=400`, change it to 700.

## Start now

**API + deploy**
1. Put the group key in `backend/.env`, then `cd backend` and run `python check_model.py`. One real call; it prints the
   raw error if anything is wrong. Do this first: the agent has been tested against a strict local stand-in for Claude,
   **not yet against the real model**.
2. Create Neon, set `DATABASE_URL`, run `python run_local.py`, chat once, restart it, and check it still remembers you.
   **Postgres has not been exercised yet** (all tests use the in-memory version).
3. Deploy (`docs/DEPLOY.md`), then `python tests/run_bench.py --url <live url>` and paste the table into `README.md`.

**Docs + demo**
- Demo story (about 90 seconds): a lead writes *"Salam, B-17 mein 3 bed ghar chahiye, budget dedh crore"* -> the agent
  understands 1.5 crore and shows a match -> *"book kar do"* -> it asks first -> *"haan ji"* books it -> a **new chat**
  still remembers the lead -> on the dashboard, another lead went quiet: run the sweep, approve the drafted follow-up.
- Best +5 chance: let one real person (a relative, a property dealer) use the live chat, with their permission, and
  screenshot it.

## What the agent can do (13 tools)

`search_listings`, `get_listing`, `check_slots`, `calculate_installment`, `save_lead_profile`, `my_data`, `forget_me`*,
`request_visit`, `reschedule_visit`, `confirm_visit`*, `cancel_visit`*, `my_visits`, `schedule_followup`.
Tools marked * run only after the lead says yes in a later message.
