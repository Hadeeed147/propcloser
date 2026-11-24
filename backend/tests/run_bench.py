"""Benchmark runner: replays tests.json (+ attacks.json) against a live /chat URL and scores them.

    python tests/run_bench.py --url http://127.0.0.1:8000
    python tests/run_bench.py --url https://<your-space>.hf.space --out ../benchmark_results.md

Each run uses fresh user ids (suffix = run id), so memory from earlier runs can't make a test pass.
Paste the printed markdown table into the README.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
# starts of service.FALLBACK and service.BUSY: a turn the model never answered must not count as a pass
NOT_ANSWERED = ("Sorry, I hit a problem", "We're handling a lot")


def check(case: dict, turns_out: list[dict]) -> tuple[bool, str]:
    rules = case.get("check", {})
    final = turns_out[-1]
    reply = final.get("reply", "")
    if any(t.get("reply", "").startswith(NOT_ANSWERED) for t in turns_out):
        return False, "fallback reply: the model call failed (see the API logs)"
    used = [c["name"] for t in turns_out for c in t.get("tool_calls", [])]
    final_tools = [c["name"] for c in final.get("tool_calls", [])]
    for tool in rules.get("expect_tools", []):
        if tool not in used:
            return False, f"expected tool {tool}, got {used or 'none'}"
    for tool in rules.get("forbid_tools", []):
        if tool in used:
            return False, f"forbidden tool {tool} was called"
    if rules.get("no_tools") and final_tools:
        return False, f"expected no tools, got {final_tools}"
    if rules.get("reply_any") and not any(s.lower() in reply.lower() for s in rules["reply_any"]):
        return False, f"reply missing any of {rules['reply_any']}"
    for s in rules.get("reply_none", []):
        if s.lower() in reply.lower():
            return False, f"reply leaked {s!r}"
    return True, "ok"


def run_case(client: httpx.Client, base: str, case: dict, run_id: str) -> dict:
    outs, latencies = [], []
    for turn in case["turns"]:
        body = {"user_id": f"{turn['user_id']}_{run_id}", "thread_id": f"{turn['thread_id']}_{run_id}",
                "message": turn["message"]}
        start = time.perf_counter()
        try:
            res = client.post(f"{base}/chat", json=body, timeout=90)
            data = res.json()
            if res.status_code != 200:
                data = {"reply": f"HTTP {res.status_code}", "tool_calls": [], "tokens": {"in": 0, "out": 0}}
        except Exception as exc:                                     # network error / timeout
            data = {"reply": f"ERROR {exc}", "tool_calls": [], "tokens": {"in": 0, "out": 0}}
        latencies.append(time.perf_counter() - start)
        outs.append(data)
    passed, why = check(case, outs)
    return {"id": case["id"], "category": case["category"], "passed": passed, "why": why,
            "latency": sum(latencies) / len(latencies),
            "tokens_in": sum(o.get("tokens", {}).get("in", 0) for o in outs),
            "tokens_out": sum(o.get("tokens", {}).get("out", 0) for o in outs),
            "reply": outs[-1].get("reply", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--tests", default=str(ROOT / "tests.json"))
    ap.add_argument("--attacks", default=str(ROOT / "attacks.json"))
    ap.add_argument("--out", default=str(ROOT / "benchmark_results.md"))
    args = ap.parse_args()
    base = args.url.rstrip("/")
    run_id = uuid.uuid4().hex[:6]

    cases = json.loads(Path(args.tests).read_text(encoding="utf-8"))
    if args.attacks and Path(args.attacks).exists():
        cases += json.loads(Path(args.attacks).read_text(encoding="utf-8"))

    with httpx.Client() as client:
        health = client.get(f"{base}/health", timeout=60).text.strip()
        print(f"/health -> {health!r}   run id {run_id}\n")
        results = []
        for case in cases:
            r = run_case(client, base, case, run_id)
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:>3}  {r['category']:<28} {r['latency']:5.1f}s  "
                  f"{r['tokens_in']:>6}/{r['tokens_out']:<5} {r['why']}")
            print(f"      reply: {r['reply'][:160]!r}")

    ours = [r for r in results if isinstance(r["id"], int)]
    attacks = [r for r in results if not isinstance(r["id"], int)]
    rate = lambda rs: f"{sum(r['passed'] for r in rs)}/{len(rs)} ({100 * sum(r['passed'] for r in rs) / max(len(rs), 1):.0f}%)"
    lines = ["| # | Category | Result | Avg latency | Tokens in/out | Notes |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['category']} | {'✅ pass' if r['passed'] else '❌ fail'} | {r['latency']:.1f}s | "
              f"{r['tokens_in']}/{r['tokens_out']} | {r['why']} |" for r in results]
    summary = (f"**Our tests:** {rate(ours)} · **Attack tests:** {rate(attacks)} · "
               f"**Avg latency:** {sum(r['latency'] for r in results) / len(results):.1f}s · "
               f"**Total tokens:** {sum(r['tokens_in'] for r in results)} in / {sum(r['tokens_out'] for r in results)} out")
    md = "\n".join([f"Benchmark run `{run_id}` against `{base}`", "", summary, "", *lines, ""])
    Path(args.out).write_text(md, encoding="utf-8")
    print("\n" + summary + f"\nMarkdown table written to {args.out}")


if __name__ == "__main__":
    main()
