# Handoff: the agent core is ready to build on

You do not need to read the agent code. This page is the contract.

## Frozen API

```
POST /chat   {"user_id": "u1", "thread_id": "t1", "message": "..."}
          -> {"reply": "...", "tool_calls": [{"name": "...", "args": {...}}], "tokens": {"in": 0, "out": 0}}
GET  /health -> ok
```

- `tool_calls` lists only tools that really ran. A tool the approval gate stopped is not listed.
- Numbers as ids, a missing `thread_id` and a null `message` are accepted. A missing `user_id` gets a 422 in the same shape. `/chat` never returns a 500.
- A reply starting with **"Sorry, I hit a problem"** means the model call failed. The real cause is in the API log on a
  line starting `CHAT FAILED`. The benchmark counts it as a fail.

Admin routes (header `X-Admin-Token`): `GET /admin/stats|leads|visits|followups`, `POST /admin/followups/{id}`
with `{"status": "approved"|"rejected"}`, and new: `POST /admin/sweep?idle_hours=24` -> `{"drafted": [...]}`, `GET /admin/usage` (dollars, cache hit rate, caps).
`GET /ready` says whether key, database and budget are fine; it needs no token and costs nothing.

## Environment variables

`ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon **direct** URL, region next to the API: US East for Hugging Face),
`ADMIN_TOKEN` (12+ characters, or the dashboard stays closed); optional `MAX_SPEND_USD` (1.80), `MAX_USD_PER_HOUR` (0.40). If you copied an old `.env` with `MAX_TOKENS=400`, change it to 700.

## Start now

**API + deploy**
1. Put the group key in `backend/.env`, then `cd backend` and run `python check_model.py`. Two real calls (under
   $0.001); raw errors are shown and the prompt cache is proven. It passes on the real model on one machine already;
   run it to prove your copy of the key.
2. Create Neon, set `DATABASE_URL`, run `python run_local.py`, chat once, restart it, and check it still remembers you.
   CI runs the same checks on a real Postgres 17; Neon itself is only proven by this step.
3. Deploy (`docs/DEPLOY.md`), check `/ready`, then `python tests/run_bench.py --url <live url>` and paste the table into `README.md`.

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
