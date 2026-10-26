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

from edgar_agent.config import TIER_ORDER, tier_for
from edgar_agent.grading import grade

RESULTS = Path("results")


def _run_agent(graph, item: dict) -> dict:
    from edgar_agent.graph import run

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
    row = {"id": item["id"], "type": item["type"], "ticker": item["ticker"],
           "tier": item.get("tier", "unknown"), "system": system,
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


def _cell(rows: list[dict]) -> str:
    if not rows:
        return "–"
    ok = sum(r["correct"] for r in rows)
    return f"{ok}/{len(rows)} ({ok / len(rows):.0%})"


def _table(title: str, header: str, groups: list[str], key: str, rows: list[dict], systems: list[str]) -> list[str]:
    lines = [f"### {title}", "", f"| {header} | " + " | ".join(systems) + " |",
             "| --- | " + " | ".join("---" for _ in systems) + " |"]
    for g in groups:
        cells = [_cell([r for r in rows if r["system"] == s and (g == "ALL" or r[key] == g)]) for s in systems]
        if all(c == "–" for c in cells):
            continue
        lines.append(f"| {'**All**' if g == 'ALL' else g} | " + " | ".join(cells) + " |")
    return lines + [""]


def summarize(rows: list[dict], model: str, n_items: int) -> str:
    for r in rows:  # results from before tiers existed get labeled from the ticker
        if r.get("tier") in (None, "unknown"):
            r["tier"] = tier_for(r["ticker"])
    systems = sorted({r["system"] for r in rows})
    types = ["lookup", "derived", "fiscal_calendar", "ALL"]
    present_tiers = {r.get("tier", "unknown") for r in rows}
    tiers = [t for t in TIER_ORDER if t in present_tiers] + sorted(present_tiers - set(TIER_ORDER)) + ["ALL"]

    lines = [f"# Eval run — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Model: `{model}` · {n_items} golden questions", ""]
    lines += _table("Accuracy by question type", "Question type", types, "type", rows, systems)
    lines += _table("Accuracy by market-cap tier", "Tier", tiers, "tier", rows, systems)

    for s in systems:
        rs = [r for r in rows if r["system"] == s]
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
    parser.add_argument("--tiers", nargs="+", help="only run these market-cap tiers, e.g. --tiers mid small")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model")
    parser.add_argument("--summarize", metavar="RUN_JSONL",
                        help="re-print the summary for an existing results/run_*.jsonl without calling any models")
    args = parser.parse_args()

    if args.summarize:
        rows = [json.loads(line) for line in Path(args.summarize).read_text().splitlines() if line.strip()]
        print(summarize(rows, "(from saved run)", len({r["id"] for r in rows})))
        return

    items = [json.loads(line) for line in Path(args.golden).read_text().splitlines() if line.strip()]
    if args.tiers:
        items = [i for i in items if i.get("tier") in args.tiers]
    items = items[: args.limit] if args.limit else items

    from edgar_agent.config import get_settings
    model = args.model or get_settings().model
    runners = {}
    if "agent" in args.systems:
        from edgar_agent.graph import build_graph

        graph = build_graph(model)
        runners["agent"] = lambda item: _run_agent(graph, item)
    if "baseline" in args.systems:
        from edgar_agent.baseline import build_baseline

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
