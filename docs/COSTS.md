# Token economics

Model: `claude-haiku-5-5`. Per million tokens: input $0.10, cached input $0.01, cache write $0.125, output $0.50
(prices checked 3 Nov 2026; confirm on the Anthropic pricing page before quoting).

## What a lead costs

Same conversation, before and after the cost work. Estimated with the prompt-cache simulator in
`backend/tests/strict_claude.py` at 3.2 characters per token; `python check_model.py` measures the real numbers.

| Conversation | Before | After | Saved | Model calls | Input read from cache |
|---|---|---|---|---|---|
| 6 turns (search, book, confirm) | $0.00110 | $0.00049 | 56% | 9 → 7 | 73% → 92% |
| 16 turns | $0.00258 | $0.00106 | 59% | 19 → 17 | 69% → 95% |

About 4,000 six-turn leads fit in $2. A guard refusal and a confirmed "yes" cost nothing at all.

## How

| Lever | What we did |
|---|---|
| Prompt caching | Order is tools, fixed rules, chat history, then the changing part (date, memory, pending action) **last**. Two breakpoints. A test fails if any request changes the cached prefix instead of extending it. |
| Fewer calls | Visit times are understood in code ("saturday 3pm", "kal 3 baje"), so booking is one tool call, not list-pick-hold. An exact "yes" runs the action and answers from a template: 0 tokens. |
| Smaller prefix | Compact tool schemas; no tool recap in the prompt; free times grouped by day. |
| Thinking off, effort low | Thinking is on by default on this model and billed as output. |
| Bounded turns | At most 5 model calls per turn; the last one must answer in words. 15 s per call, one retry. |
| Small memory | Facts and notes have length limits, because memory is sent on every call. |

## Guard rails

`/chat` has to be open, so a script could try to burn the key.

- `MAX_USD_PER_HOUR` (0.40) limits how fast money can leave. Forty full 16-turn leads cost about $0.04.
- `MAX_SPEND_USD` (1.80) keeps a margin under the $2 limit. The running total is stored in Postgres, so a restart does not
  reset it. It only counts calls made by this server, not calls from your laptops.
- At a cap the API stays up and answers "please try again in a few minutes" without calling the model.
- `GET /admin/usage` shows dollars, calls, cache hit rate and caps. If the cache hit rate drops below about 70% in a busy
  conversation, something is changing the prefix.
- `tests/test_e2e.py` fails if a typical lead goes above $0.0008.

## Unit economics for the pitch

At PKR 15,000 per agency per month and about 280 PKR per dollar, even 1,000 leads a month cost roughly $0.50 (PKR 140) in
model calls: under 1% of the fee. Hosting and people, not tokens, decide the margin. (Exchange rate is an assumption.)
