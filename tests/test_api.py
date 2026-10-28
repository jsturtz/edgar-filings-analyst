import pytest

pytest.importorskip("fastapi")
pytest.importorskip("prometheus_client")

from fastapi.testclient import TestClient  # noqa: E402

from edgar_agent.api import create_app  # noqa: E402
from edgar_agent.schemas import AgentAnswer, Citation  # noqa: E402


def fake_runner(question: str) -> dict:
    return {
        "answer": AgentAnswer(
            answer="Toro's fiscal 2024 revenue was $4.58 billion.",
            value=4_580_000_000,
            unit="USD",
            period_end="2024-11-01",
            citations=[Citation(source="xbrl", ticker="TTC", fiscal_year=2024, detail="us-gaap:Revenues")],
        ),
        "grounded": True,
        "grounding_reason": "matched evidence value",
        "tool_calls": 2,
    }


def failing_runner(question: str) -> dict:
    raise RuntimeError("model API down")


def client(runner=fake_runner, ready=(True, "ready")):
    return TestClient(create_app(runner=runner, readiness=lambda: ready))


def test_healthz():
    with client() as c:
        assert c.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_not_ready_with_503():
    with client(ready=(False, "vector index is empty; run ingest")) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert r.json()["reason"].startswith("vector index is empty")


def test_readyz_ok():
    with client() as c:
        assert c.get("/readyz").status_code == 200


def test_ask_returns_structured_answer():
    with client() as c:
        r = c.post("/ask", json={"question": "What was Toro's revenue in fiscal 2024?"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"]["value"] == 4_580_000_000
        assert body["answer"]["citations"][0]["ticker"] == "TTC"
        assert body["grounded"] is True
        assert body["tool_calls"] == 2
        assert body["latency_s"] >= 0


def test_ask_validates_input():
    with client() as c:
        assert c.post("/ask", json={"question": "?"}).status_code == 422


def test_agent_failure_is_502_and_counted():
    with client(runner=failing_runner) as c:
        r = c.post("/ask", json={"question": "What was Toro's revenue?"})
        assert r.status_code == 502
        assert 'edgar_ask_requests_total{status="error"} 1.0' in c.get("/metrics").text


def test_metrics_track_answers():
    with client() as c:
        c.post("/ask", json={"question": "What was Toro's revenue in fiscal 2024?"})
        text = c.get("/metrics").text
        assert 'edgar_answers_total{grounded="true"} 1.0' in text
        assert "edgar_ask_latency_seconds_bucket" in text
        assert "edgar_tool_calls_per_question_count 1.0" in text
