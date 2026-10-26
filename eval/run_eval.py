"""Run the golden dataset against the agent and the no-retrieval baseline.

    uv run python eval/run_eval.py                 # full run, both systems
    uv run python eval/run_eval.py --limit 10      # quick smoke test
    uv run python eval/run_eval.py --systems agent

Writes per-question results to results/run_<timestamp>.jsonl and a markdown summary
to results/summary_<timestamp>.md (also printed).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from edgar_agent.baseline import build_baseline
from edgar_agent.grading import grade
from edgar_agent.graph import build_graph, run

RESULTS = Path("results")


def _run_agent(graph, item: dict) -> dict:
    state = run(item["question"], graph)
    ans = state["answer"]
    tool_calls = sum(len(getattr(m, "tool_calls", []) or []) for m in state["messages"])
    return {"answer": ans.model_dump(), "grounded": state["grounded"],
            "grounding_reason": state["grounding_reason"], "retries": state["retries"],
            "tool_calls": tool_calls}


def _run_baseline(answer_fn, item: dict) -> dict:
    return {"answer": answer_fn(item["question"]).model_dump()}


def evaluate_one(system: str, runner, item: dict) -> dict:
    started = time.perf_counter()
    row = {"id": item["id"], "type": item["type"], "ticker": item["ticker"], "system": system,
           "question": item["question"], "expected": item["expected"]}
    try:
        row.update(runner(item))
        a = row["answer"]
        g = grade(item, a.get("value"), a.get("unit"), a.get("answer", ""))
        row.update(correct=g.correct, grade_detail=g.detail)
    except Exception as exc:  # keep the run going; errors count as wrong
        row.update(correct=False, error=f"{type(exc).__name__}: {exc}")
    row["latency_s"] = round(time.perf_counter() - started, 2)
    return row


def summarize(rows: list[dict], model: str, n_items: int) -> str:
    by = defaultdict(list)
    for r in rows:
        by[(r["system"], r["type"])].append(r)
        by[(r["system"], "ALL")].append(r)
    systems = sorted({r["system"] for r in rows})
    types = ["lookup", "derived", "fiscal_calendar", "ALL"]

    lines = [f"# Eval run — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Model: `{model}` · {n_items} golden questions", "",
             "| Question type | " + " | ".join(systems) + " |",
             "| --- | " + " | ".join("---" for _ in systems) + " |"]
    for t in types:
        cells = []
        for s in systems:
            rs = by.get((s, t), [])
            cells.append(f"{sum(r['correct'] for r in rs)}/{len(rs)} ({sum(r['correct'] for r in rs) / len(rs):.0%})" if rs else "–")
        lines.append(f"| {'**All**' if t == 'ALL' else t} | " + " | ".join(cells) + " |")

    lines.append("")
    for s in systems:
        rs = by[(s, "ALL")]
        lat = sum(r["latency_s"] for r in rs) / len(rs)
        errs = sum("error" in r for r in rs)
        extra = ""
        if s == "agent":
            grounded = [r for r in rs if r.get("grounded") is not None]
            if grounded:
                extra = f", grounded {sum(r['grounded'] for r in grounded)}/{len(grounded)}"
            extra += f", avg tool calls {sum(r.get('tool_calls', 0) for r in rs) / len(rs):.1f}"
        lines.append(f"- **{s}**: avg latency {lat:.1f}s, errors {errs}{extra}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", default="eval/golden.jsonl")
    parser.add_argument("--systems", nargs="+", default=["baseline", "agent"], choices=["baseline", "agent"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model")
    args = parser.parse_args()

    items = [json.loads(line) for line in Path(args.golden).read_text().splitlines() if line.strip()]
    items = items[: args.limit] if args.limit else items

    from edgar_agent.config import get_settings
    model = args.model or get_settings().model
    runners = {}
    if "agent" in args.systems:
        graph = build_graph(model)
        runners["agent"] = lambda item: _run_agent(graph, item)
    if "baseline" in args.systems:
        answer_fn = build_baseline(model)
        runners["baseline"] = lambda item: _run_baseline(answer_fn, item)

    jobs = [(s, r, item) for s, r in runners.items() for item in items]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda j: evaluate_one(*j), jobs))

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"run_{stamp}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = summarize(rows, model, len(items))
    (RESULTS / f"summary_{stamp}.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
