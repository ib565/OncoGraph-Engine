from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from api import main
from pipeline.types import PipelineError, QueryEngineResult


class StubEngine:
    def __init__(self, runner: Callable[[str], QueryEngineResult]):
        self._runner = runner
        self.trace = None

    def run(self, question: str) -> QueryEngineResult:
        return self._runner(question)


class ErrorEngine:
    def __init__(self, exc: Exception):
        self._exc = exc
        self.trace = None

    def run(self, question: str) -> QueryEngineResult:  # type: ignore[override]
        raise self._exc


@pytest.fixture
def app_client() -> TestClient:
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


def test_healthz_endpoint(app_client: TestClient) -> None:
    response = app_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_success(app_client: TestClient) -> None:
    main.app.dependency_overrides[main.get_engine] = lambda: StubEngine(
        lambda question: QueryEngineResult(
            answer=f"Answer for {question}",
            cypher="MATCH (n) RETURN n",
            rows=[{"gene_symbol": "KRAS"}],
        )
    )

    response = app_client.post("/query", json={"question": "Tell me about KRAS"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("Answer for")
    assert payload["cypher"] == "MATCH (n) RETURN n"
    assert payload["rows"] == [{"gene_symbol": "KRAS"}]


def test_query_pipeline_error_returns_400(app_client: TestClient) -> None:
    main.app.dependency_overrides[main.get_engine] = lambda: ErrorEngine(
        PipelineError("validation failed", step="validate_cypher")
    )

    response = app_client.post("/query", json={"question": "Invalid"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["message"] == "validation failed"
    assert payload["detail"]["step"] == "validate_cypher"


def test_query_unhandled_error_returns_500(app_client: TestClient) -> None:
    main.app.dependency_overrides[main.get_engine] = lambda: ErrorEngine(ValueError("boom"))

    response = app_client.post("/query", json={"question": "KRAS"})

    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["message"] == "boom"


def test_query_returns_run_id(app_client: TestClient) -> None:
    main.app.dependency_overrides[main.get_engine] = lambda: StubEngine(
        lambda question: QueryEngineResult(
            answer=f"Answer for {question}",
            cypher="MATCH (n) RETURN n",
            rows=[{"gene_symbol": "KRAS"}],
        )
    )

    response = app_client.post("/query", json={"question": "Tell me about KRAS"})

    assert response.status_code == 200
    payload = response.json()
    assert "run_id" in payload
    assert isinstance(payload["run_id"], str)
    assert len(payload["run_id"]) > 0


def test_feedback_success(app_client: TestClient) -> None:
    # Create a mock trace sink to capture feedback
    import json
    import tempfile
    from pathlib import Path

    from pipeline.trace import JsonlTraceSink

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_file = Path(tmpdir) / "test_trace.jsonl"
        trace_sink = JsonlTraceSink(trace_file)

        # Create a stub engine with trace
        class StubEngineWithTrace:
            def __init__(self):
                self.trace = trace_sink

            def run(self, question: str) -> QueryEngineResult:
                return QueryEngineResult(
                    answer=f"Answer for {question}",
                    cypher="MATCH (n) RETURN n",
                    rows=[{"gene_symbol": "KRAS"}],
                )

        main.app.dependency_overrides[main.get_engine] = lambda: StubEngineWithTrace()

        # Submit feedback
        response = app_client.post("/query/feedback", json={"run_id": "test-run-123", "cypher_correct": True})

        assert response.status_code == 200
        payload = response.json()
        assert payload["message"] == "Feedback recorded successfully"

        # Verify feedback was recorded to trace
        assert trace_file.exists()
        contents = trace_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(contents) == 1
        trace_data = json.loads(contents[0])
        assert trace_data["step"] == "user_feedback"
        assert trace_data["run_id"] == "test-run-123"
        assert trace_data["cypher_correct"] is True


def test_feedback_no_trace_returns_400(app_client: TestClient) -> None:
    # Create a stub engine without trace
    class StubEngineNoTrace:
        def __init__(self):
            self.trace = None

        def run(self, question: str) -> QueryEngineResult:
            return QueryEngineResult(
                answer=f"Answer for {question}",
                cypher="MATCH (n) RETURN n",
                rows=[{"gene_symbol": "KRAS"}],
            )

    main.app.dependency_overrides[main.get_engine] = lambda: StubEngineNoTrace()

    response = app_client.post("/query/feedback", json={"run_id": "test-run-123", "cypher_correct": True})

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Tracing not available"


def test_feedback_invalid_request(app_client: TestClient) -> None:
    # Test missing run_id
    response = app_client.post("/query/feedback", json={"cypher_correct": True})
    assert response.status_code == 422  # Validation error

    # Test missing cypher_correct
    response = app_client.post("/query/feedback", json={"run_id": "test-run-123"})
    assert response.status_code == 422  # Validation error
