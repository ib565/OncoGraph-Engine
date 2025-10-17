from __future__ import annotations

from typing import Callable

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

