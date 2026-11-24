# Token economics

Model: `claude-haiku-5-5`. Per million tokens: input $0.10, cached input $0.01, cache write $0.125, output $0.50
(prices checked 3 Nov 2026; confirm on the Anthropic pricing page before quoting).

## What a lead costs (measured on the real model, 24 Nov 2026, local server)

| Conversation | Cost per lead | Model calls | Input read from cache | Reply time (p50 / p95) | Leads per $2 |
|---|---|---|---|---|---|
| 6 turns (search, book, confirm, recall) | **$0.0008** | 7 | 91% | 1.0 s / 2.7 s | about 2,400 |
| 16 turns (several searches, installment, booking) | **$0.0032** | 22 | 88% | 1.1 s / 2.6 s | about 620 |
| The whole 15-case benchmark, once | **about $0.003** | 24 | 91% | 1.3 s average | about 650 runs |

A guard refusal and a confirmed "yes" cost nothing at all.

An offline simulator (`backend/tests/strict_claude.py`) compares versions without spending money. It showed the cost work
saving 56-59% per conversation, but it underestimates real cost by about 2-3 times because real replies and tool calls are
longer. Use it for "did this change make things worse", use the table above for money.

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

- `MAX_USD_PER_HOUR` (0.40) limits how fast money can leave. A hundred full 16-turn leads an hour fit inside it.
- `MAX_SPEND_USD` (1.80) keeps a margin under the $2 limit. The running total is stored in Postgres, so a restart does not
  reset it. It only counts calls made by this server, not calls from your laptops.
- At a cap the API stays up and answers "please try again in a few minutes" without calling the model.
- `GET /admin/usage` shows dollars, calls, cache hit rate and caps. If the cache hit rate drops below about 70% in a busy
  conversation, something is changing the prefix.
- `tests/test_e2e.py` fails if a typical lead goes above $0.0008 in the simulator.

## Unit economics for the pitch

At PKR 15,000 per agency per month and about 280 PKR per dollar, even 1,000 long conversations a month cost roughly $3.20 (about PKR 900)
in model calls: about 6% of the fee; short ones, under 2%. Hosting and people, not tokens, decide the margin. (Exchange rate is an assumption.)
