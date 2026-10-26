# EDGAR Filings Analyst

A LangGraph agent that answers questions about US public companies **from their SEC 10-K
filings**, with a golden-dataset evaluation that measures how much retrieval actually beats
the same model answering from memory.

> "What was Home Depot's revenue in fiscal 2024?" sounds easy. A model answering from memory
> has to know that Home Depot's fiscal 2024 ended in **February 2025**, that the 10-K reports
> figures in millions, and which of several revenue tags is the headline number. It also has
> to remember the number exactly. This project measures how often it gets all of that right,
> and how much a retrieval agent with exact-figure tools improves on it.

## Why EDGAR

- **Precision:** answers are exact numbers, so they can be graded automatically. A model that
  "roughly knows" a company's financials still gets graded wrong.
- **Freshness and long tail:** new filings arrive every quarter, after any model's training
  cutoff, and smaller companies are barely memorized at all.
- **Real retrieval problems:** 300-page documents, financial tables, prior-year comparatives that
  look like current figures, and companies with non-calendar fiscal years.

## How it works

```mermaid
flowchart LR
    Q([Question]) --> A[agent<br/>Claude + tools]
    A -- tool calls --> T[tools]
    T --> A
    A -- done --> F[finalize<br/>structured answer]
    F --> V{verify<br/>grounding check}
    V -- number not in evidence<br/>1 retry --> A
    V -- grounded --> R([AgentAnswer + citations])
```

**Tools**

| Tool | What it does |
| --- | --- |
| `get_financial_metric` | Exact annual figure from the SEC's XBRL data (revenue, net income, assets, cash flow, EPS…), resolved to the company's own fiscal-year label |
| `list_fiscal_years` | The fiscal years on file and the date each one ended, so the agent can resolve "fiscal 2024" correctly |
| `search_filings` | Semantic search over 10-K text, filterable by ticker, fiscal year and Item (MD&A, Risk Factors…) |
| `calculate` | Safe arithmetic (an AST evaluator, not `eval`), so margins and growth rates are never mental math |

**Guardrails**

- **Structured output:** every answer is a Pydantic `AgentAnswer` with a value, unit, period end
  date and citations to an XBRL concept, a 10-K Item, or a calculation.
- **Deterministic grounding check:** the `verify` node rejects any headline number that doesn't
  appear in a tool result (allowing for "in millions" scaling) and sends the agent back once
  with feedback. This catches a model that retrieves the right document and then reports a
  remembered number anyway.

**Ingestion:** `sec_client.py` downloads filings politely (required User-Agent, under the
SEC's 10 requests/second limit, with a disk cache). `parse_10k.py` strips the hidden inline-XBRL
data, flattens tables into `label | value | value` rows, and splits the document by Item. It keeps
the longest match for each heading, which skips the table of contents. Chunks are embedded
locally with `BAAI/bge-small-en-v1.5` into Chroma, with ticker, fiscal year and Item metadata.

## Evaluation

`eval/build_golden.py` builds the golden dataset from the companies' own XBRL-tagged
figures. Derived answers (margins, growth) are computed in Python, never by an LLM.

| Type | Example | Graded as |
| --- | --- | --- |
| `lookup` | Total revenue / net income / total assets / operating cash flow for fiscal year N | within ±0.5% |
| `derived` | Gross margin, net margin, year-over-year revenue growth | within ±0.3 percentage points |
| `fiscal_calendar` | "In which calendar month did fiscal year N end?" | exact month |

`eval/run_eval.py` runs every question through **(a) the agent** and **(b) a no-retrieval
baseline**: the same model and output schema, answering from memory. It reports accuracy by
question type, grounding rate, tool calls and latency.

### Results

_First run pending. See `results/` for the latest `summary_*.md`._

### Caveats

- Ground truth for `lookup` questions comes from the same XBRL data the agent's
  `get_financial_metric` tool reads. That is deliberate: the eval measures whether the agent
  *uses* authoritative data correctly (picks the right company, fiscal year, metric and units,
  and computes derived figures correctly), compared with a model answering from memory. It is
  not an independent audit of the SEC data itself.
- Companies tag some figures inconsistently (for example, revenue under different XBRL
  concepts). The lookup tries candidate tags in priority order and falls back to text search.
- The grounding check matches numbers, not meaning. It can be fooled by a coincidental match
  in retrieved text. It is a cheap first line of defense, not proof of correctness.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY and SEC_USER_AGENT ("Name email@example.com")
uv sync

# 1. Download and index 3 years of 10-Ks for the default 10 companies (~10 minutes the first time)
uv run python -m edgar_agent.ingest --years 3

# 2. Ask a question
uv run python -m edgar_agent.ask "What was Home Depot's gross margin in fiscal 2024?"

# 3. Build the golden set and run the eval
uv run python eval/build_golden.py
uv run python eval/run_eval.py --limit 10     # smoke test
uv run python eval/run_eval.py                # full run, agent vs. baseline

# Unit tests (parsing, XBRL lookup, grounding, grading)
uv run pytest
```

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env` to trace every agent run in
LangSmith.

## Layout

```
src/edgar_agent/
  sec_client.py   EDGAR client: User-Agent, rate limit, disk cache
  parse_10k.py    10-K HTML -> clean text -> Item sections
  xbrl.py         fiscal-year-aware exact figures from companyfacts JSON
  ingest.py       download, chunk, embed into Chroma
  tools.py        agent tools
  graph.py        LangGraph workflow (agent -> tools -> finalize -> verify)
  grounding.py    deterministic number-in-evidence check
  schemas.py      AgentAnswer / Citation (Pydantic)
  baseline.py     no-retrieval control
  grading.py      golden-answer grading
eval/
  build_golden.py golden dataset from XBRL ground truth
  run_eval.py     agent vs. baseline runner and report
tests/            unit tests with fixture 10-K HTML and companyfacts JSON
```

## Roadmap

- Text questions ("why did gross margin change?") graded against hand-written key facts with an LLM judge
- Hybrid retrieval (BM25 + embeddings) and reranking for table-heavy passages
- 10-Q and 8-K ingestion to test freshness on events after a model's training cutoff
- Docker Compose for one-command setup
