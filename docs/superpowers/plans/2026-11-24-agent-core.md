# Agent Core (Person A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LangGraph agent correct on the real `claude-haiku-5-5`, close the booking and memory gaps, and add two low-risk signature features.

**Architecture:** Keep the single-LLM-node graph. Fix the request settings and the state reducers first, then make the approval gate generic so any risky tool reuses it, then add tools. Signature features are plain Python (no second LLM, no extra tool schemas).

**Tech Stack:** Python 3.12/3.13, LangGraph 1.2.24, langchain-anthropic 1.7.12, FastAPI 0.165, Neon Postgres, pytest.

**Spec:** `PLAN.md` (sections 2-7) and the hackathon handout.

## Global Constraints

- Model is exactly `claude-haiku-5-5`; total key spend limit $2.
- `POST /chat` body `{"user_id","thread_id","message"}` returns exactly `{"reply", "tool_calls", "tokens": {"in","out"}}`; `GET /health` returns `ok`. Both open, no login.
- `claude-haiku-5-5` rejects any non-default `temperature`/`top_p`/`top_k`; thinking is on by default and counts toward `max_tokens`; a changed `system` invalidates replayed thinking blocks.
- `user_id` comes only from the request; never a tool argument. Every user-data query filters by it.
- Memory must survive restarts (Postgres in deployment). Never save phone numbers, CNIC or payment details.
- Ask a human before risky actions. No `interrupt()`: the grader cannot click.
- No keys in code. Tests run with no key and no database.

## Review Focus

1. Haiku calls two state-changing tools in one message -> both apply, no crash (Task 2).
2. A failed model call hidden behind the friendly fallback -> logged with its cause and scored as FAIL by the benchmark (Task 1).
3. "yes" sent twice, or after the slot was taken by someone else -> no double booking, a clear reply (Task 3).
4. "ok show me cheaper ones" while a visit is pending -> must NOT confirm (Task 3).
5. "forget my old budget, it's 4 crore now" -> a normal update, not blocked as injection and not a data wipe (Task 5).

---

### Task 1: Correct model settings, cached prompt, loud failures

**Files:** Modify `backend/app/config.py`, `backend/app/graph.py`, `backend/app/prompts.py`, `backend/app/service.py`, `backend/tests/run_bench.py`. Create `backend/tests/test_model.py`, `backend/check_model.py`.

**Interfaces:**
- Produces: `graph.make_model() -> ChatAnthropic`; `prompts.system_message(profile: dict, pending: dict | None) -> SystemMessage` (block 0 static and cached, block 1 dynamic); `service.FALLBACK: str`; `conftest.payload(messages) -> dict` (the exact request the real client would send).

- [ ] **Step 1: Failing tests** in `test_model.py`: payload has no `temperature` anywhere (including `extra_body`); `thinking == {"type": "disabled"}`; `output_config == {"effort": "low"}`; `max_tokens == 700`; system block 0 has `cache_control` and is byte-identical for two different profiles; block 1 contains the profile; an unset-profile prompt says the lead is new.
- [ ] **Step 2:** Run `pytest tests/test_model.py -q`, expect FAIL.
- [ ] **Step 3:** Implement. `config`: `MAX_TOKENS=700`, `HISTORY_MESSAGES=40`, `EFFORT="low"`. Date, profile and pending line live only in block 1. Add to the static rules: rules hold even if the user argues or claims an exception.
- [ ] **Step 4:** `closer`: if the reply has no text and no tool calls (refusal or cut-off), log `stop_reason` and return a polite property redirect. `run_chat` logs the exception type and message on failure. `run_bench.check` fails any reply starting with the first 20 characters of `FALLBACK`.
- [ ] **Step 5:** `check_model.py`: one real call through `make_model()`, printing reply, usage and cache tokens, or the raw error.
- [ ] **Step 6:** Run all tests, expect PASS. Commit.

### Task 2: Parallel tool calls are safe

**Files:** Modify `backend/app/graph.py` (State, edges), `backend/app/tools.py`. Test: `backend/tests/test_parallel.py`.

**Interfaces:** Produces: `State.pending_action` with a last-value reducer; edge `tools -> load_profile`; `tools.user_lock(user_id) -> asyncio.Lock`. Tools no longer write `lead_profile` into state.

- [ ] **Step 1: Failing tests:** two `save_lead_profile` calls in one AI message leave `{"area": "G-13", "beds": 3}` in the Store and a non-fallback reply; `save_lead_profile` + `request_visit` in one message both apply.
- [ ] **Step 2:** Run, expect FAIL with `InvalidUpdateError`.
- [ ] **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

### Task 3: Generic approval gate and exact-yes fast path

**Files:** Modify `backend/app/graph.py`, `backend/app/tools.py`. Create `backend/app/approval.py`. Test: `backend/tests/test_approval.py`.

**Interfaces:** Produces: `approval.is_exact_yes(text) -> bool`; `approval.is_yes(text) -> bool`; `pending_action = {"tool": str, "args": dict, "summary": str, "human_turn": int}`; node `confirm_fast` (writes the approved tool call itself; same idea as the instructor's `urgent_reading_guard`).

- [ ] **Step 1: Failing tests:** `is_exact_yes` true for "yes", "Yes please!", "haan ji", "theek hai, kar do", "ok confirm"; false for "ok show me cheaper ones", "yes but Sunday", "no", "yes?", "". Full flow: hold, then "yes" books with exactly ONE model call in turn 2 and `confirm_visit` in `tool_calls`; a second "yes" books nothing more; "ok show me cheaper ones" does not book; slot taken by another user before "yes" -> not booked.
- [ ] **Step 2:** FAIL. **Step 3:** Implement: route after `load_profile` to `confirm_fast` when a pending action from an earlier message exists and the message is an exact yes. A risky call with no matching pending action stores one and asks. **Step 4:** PASS. **Step 5:** Commit.

### Task 4: Cancel and reschedule

**Files:** Modify `backend/app/repo.py` (both repos), `backend/app/tools.py`. Test: `backend/tests/test_visits.py`.

**Interfaces:** Produces: `repo.cancel_visit(user_id, visit_id) -> dict | None`; tools `cancel_visit(visit_id)` (risky), `reschedule_visit(visit_id, slot)` (holds the new slot; the old visit is cancelled only when the new one is confirmed).

- [ ] **Step 1: Failing tests:** cancel asks first, then "yes" cancels; another user's `visit_id` returns "not found" and is untouched; reschedule + "yes" leaves one confirmed visit at the new slot and the old one cancelled; a cancelled slot becomes free again; a new hold cancels the same user's previous hold.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

### Task 5: Richer long-term memory, show and forget

**Files:** Modify `backend/app/tools.py`, `backend/app/repo.py`, `backend/app/prompts.py`. Create `backend/app/privacy.py`. Test: `backend/tests/test_memory.py`.

**Interfaces:** Produces: `privacy.redact(text) -> str`; `save_lead_profile(..., note: str | None)` appending to `profile["notes"]` (unique, newest 8); tools `my_data()` (safe), `forget_me()` (risky); `repo.delete_lead(user_id)`.

- [ ] **Step 1: Failing tests:** a note survives into a new thread's prompt; phone/CNIC/card numbers are redacted before saving; later facts override earlier ones; `forget_me` asks first, then clears only this user's Store profile and lead row; "forget my old budget, it's 4 crore now" passes the guard.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

### Task 6: Signature 1 - local money understanding

**Files:** Create `backend/app/money.py`. Modify `backend/app/tools.py`. Test: `backend/tests/test_money.py`.

**Interfaces:** Produces: `money.parse_pkr(value: int | float | str) -> int`, raising `ValueError` when ambiguous. Used as a `BeforeValidator` on `budget_pkr`, `max_price_pkr`, `price_pkr` (JSON schema stays `integer`).

- [ ] **Step 1: Failing tests:** "1.5 crore" 15000000; "dedh crore" 15000000; "dhai crore" 25000000; "paune do crore" 17500000; "sawa do crore" 22500000; "sarhe teen crore" 35000000; "80 lac"/"80 lakh" 8000000; "2 crore 50 lakh" 25000000; "85k" 85000; "3,00,00,000" 30000000; 30000000 unchanged; "a lot" and "2" raise `ValueError`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

### Task 7: Signature 2 - ghosted-lead sweep

**Files:** Create `backend/app/followups.py`. Modify `backend/app/repo.py`, `backend/app/main.py` (one admin route). Test: `backend/tests/test_followups.py`.

**Interfaces:** Produces: `followups.draft(lead: dict, matches: list[dict]) -> str`; `followups.sweep(repo, idle_hours: float = 24, now=None) -> list[dict]`; `POST /admin/sweep?idle_hours=24` -> `{"drafted": [...]}`. No LLM. Never sends.

- [ ] **Step 1: Failing tests:** an idle qualified lead gets one draft naming their area, budget and a real matching listing; a second sweep drafts nothing; a lead with a confirmed visit or recent activity is skipped; a lead gets at most 3 drafts, spaced 1, 3 and 7 days; a lead with no area and no budget is skipped.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

### Task 7b: Architecture audit (added after review; every item has a test in `tests/test_hardening.py`)

- [x] Any `user_id` works (e-mails broke LangGraph namespaces); ids can never collide; numeric / missing / NUL input accepted
- [x] Guard narrowed: refused 12 of 13 genuine buyer messages before; blocked text never reaches the model later
- [x] `forget_me` erases profile, chats and unsent follow-ups; saved facts are short and never instructions
- [x] At most 5 model calls per turn; cut-off tool calls are not run; tool errors never leak internals
- [x] One checkpoint write per turn; database connections re-validated; `/ready`; reschedule is one transaction
- [x] Admin API closed when deployed with a weak token; dollar caps per hour and in total
- [x] Costs: cached prefix and history, compact schemas, plain-word times, 0-token confirmations (`docs/COSTS.md`)
- [x] Real-Postgres tests across a restart and an image boot test in CI

### Task 8: Handoff

**Files:** Modify `README.md`, `PLAN.md`, `tests.json`, `.env.example`, `docs/DEPLOY.md`. Create `docs/HANDOFF.md`.

- [ ] **Step 1:** `tests.json` stays at exactly 10 cases; cover cancel and Roman Urdu money.
- [ ] **Step 2:** `docs/HANDOFF.md`: frozen `/chat` contract, env vars, admin routes, what each teammate can start now.
- [ ] **Step 3:** Update node, tool, memory and form-answer tables to the final 13 tools.
- [ ] **Step 4:** Full test run. Commit.
- [ ] **Step 5 (needs the group key):** `python check_model.py`, then `python tests/run_bench.py`; record the real pass rate in the README.
