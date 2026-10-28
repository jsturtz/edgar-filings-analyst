"""HTTP API for running the agent as a service (for Docker / Kubernetes).

    uv run uvicorn edgar_agent.api:app --port 8000

Endpoints
    POST /ask      {"question": "..."} -> structured answer + grounding result
    GET  /healthz  liveness: the process is up (no external calls)
    GET  /readyz   readiness: the vector index and SEC cache exist (503 until ingest has run)
    GET  /metrics  Prometheus metrics

The agent and the readiness check are injectable so tests can run without models or data.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from .config import get_settings
from .schemas import AgentAnswer

# A runner takes a question and returns {"answer": AgentAnswer, "grounded": bool | None,
# "grounding_reason": str | None, "tool_calls": int}.
Runner = Callable[[str], dict]
# A readiness check returns (ready, reason).
Readiness = Callable[[], tuple[bool, str]]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class AskResponse(BaseModel):
    answer: AgentAnswer
    grounded: bool | None
    grounding_reason: str | None
    tool_calls: int
    latency_s: float


class Metrics:
    """Prometheus metrics on a per-app registry (so tests can create many apps)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "edgar_ask_requests_total", "Ask requests by outcome", ["status"], registry=self.registry
        )
        self.latency = Histogram(
            "edgar_ask_latency_seconds", "End-to-end latency of /ask",
            buckets=(0.5, 1, 2, 4, 8, 16, 32, 64), registry=self.registry,
        )
        self.answers = Counter(
            "edgar_answers_total", "Answers by grounding result", ["grounded"], registry=self.registry
        )
        self.tool_calls = Histogram(
            "edgar_tool_calls_per_question", "Tool calls the agent made per question",
            buckets=(0, 1, 2, 3, 4, 6, 8, 12), registry=self.registry,
        )
        self.llm_requests = Counter(
            "edgar_llm_questions_total", "Questions answered, by LLM provider", ["provider"],
            registry=self.registry,
        )


def default_runner() -> Runner:
    """Build the LangGraph agent once and reuse it for every request."""
    from .graph import build_graph, run

    graph = build_graph()

    def runner(question: str) -> dict:
        state = run(question, graph)
        tool_calls = sum(len(getattr(m, "tool_calls", None) or []) for m in state["messages"])
        return {
            "answer": state["answer"],
            "grounded": state["grounded"],
            "grounding_reason": state["grounding_reason"],
            "tool_calls": tool_calls,
        }

    return runner


def default_readiness() -> tuple[bool, str]:
    """Ready once ingest has populated the SEC cache and the vector index."""
    settings = get_settings()
    cache = settings.cache_dir
    if not cache.exists() or not any(cache.iterdir()):
        return False, f"SEC cache at {cache} is empty; run ingest"
    try:
        from .store import get_store

        if not get_store().get(limit=1)["ids"]:
            return False, "vector index is empty; run ingest"
    except Exception as exc:  # report, don't crash the probe
        return False, f"vector store unavailable: {type(exc).__name__}: {exc}"
    return True, "ready"


def create_app(runner: Runner | None = None, readiness: Readiness | None = None) -> FastAPI:
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if runner is None:
            from .store import get_store

            get_store()  # load the embedding model at startup, not on the first request
        app.state.runner = runner or default_runner()
        app.state.readiness = readiness or default_readiness
        yield

    app = FastAPI(title="EDGAR Filings Analyst", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict:
        ready, reason = app.state.readiness()
        if not ready:
            response.status_code = 503
        return {"ready": ready, "reason": reason}

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest) -> AskResponse:
        # A plain `def` endpoint: FastAPI runs it in a worker thread, so the blocking
        # agent call doesn't stall the event loop (or the health probes).
        started = time.perf_counter()
        try:
            result = app.state.runner(req.question)
        except Exception as exc:
            metrics.requests.labels(status="error").inc()
            raise HTTPException(status_code=502, detail=f"agent failed: {type(exc).__name__}: {exc}")
        elapsed = time.perf_counter() - started

        metrics.requests.labels(status="ok").inc()
        metrics.latency.observe(elapsed)
        metrics.answers.labels(grounded=str(result["grounded"]).lower()).inc()
        metrics.tool_calls.observe(result["tool_calls"])
        metrics.llm_requests.labels(provider=get_settings().provider).inc()
        return AskResponse(**result, latency_s=round(elapsed, 3))

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app


def __getattr__(name: str):
    # `uvicorn edgar_agent.api:app` builds the real app lazily, so importing this module
    # (e.g. in tests) never loads models.
    if name == "app":
        return create_app()
    raise AttributeError(name)
