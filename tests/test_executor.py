"""Unit tests for the Neo4j executor adapter."""

from __future__ import annotations

import pytest

from pipeline import PipelineConfig
from pipeline.executor import Neo4jExecutor
from pipeline.types import PipelineError


class FakeRecord:
    def __init__(self, data: dict[str, object]):
        self._data = data

    def data(self) -> dict[str, object]:
        return self._data


class FakeResult:
    def __init__(self, records: list[FakeRecord]):
        self._records = records

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self._records)


class FakeTx:
    def __init__(self):
        self.last_kwargs: dict[str, object] | None = None

    def run(self, cypher: str, *, timeout: float, fetch_size: int):
        self.last_kwargs = {
            "cypher": cypher,
            "timeout": timeout,
            "fetch_size": fetch_size,
        }
        record = FakeRecord(
            {
                "name": "Cetuximab",
                "pmids": ["12345", "67890"],
                "tags": "EGFR;Monoclonal",
            }
        )
        return FakeResult([record])


class FakeSession:
    def __init__(self, expected_timeout: float):
        self.expected_timeout = expected_timeout
        self.tx = FakeTx()

    # Context manager protocol
    def __enter__(self):  # pragma: no cover - trivial
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        return False

    def execute_read(self, func, cypher: str):
        return func(self.tx, cypher)


class FakeDriver:
    def __init__(self, session: FakeSession):
        self._session = session
        self.last_session_timeout: float | None = None
        self.closed = False

    def session(self, *, timeout: float):
        self.last_session_timeout = timeout
        assert timeout == self._session.expected_timeout
        return self._session

    def close(self):  # pragma: no cover - trivial
        self.closed = True


def test_executor_runs_query_with_configured_limits(monkeypatch):
    config = PipelineConfig(neo4j_timeout_seconds=12.5, neo4j_fetch_size=250)
    fake_session = FakeSession(expected_timeout=config.neo4j_timeout_seconds)
    fake_driver = FakeDriver(fake_session)

    monkeypatch.setattr(
        "pipeline.executor.GraphDatabase",
        type("_GraphDatabase", (), {"driver": staticmethod(lambda uri, auth: fake_driver)}),
    )

    executor = Neo4jExecutor(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        config=config,
    )

    rows = executor.execute_read("MATCH (g:Gene) RETURN g")

    assert fake_driver.last_session_timeout == config.neo4j_timeout_seconds
    assert fake_session.tx.last_kwargs == {
        "cypher": "MATCH (g:Gene) RETURN g",
        "timeout": config.neo4j_timeout_seconds,
        "fetch_size": config.neo4j_fetch_size,
    }
    assert rows == [
        {
            "name": "Cetuximab",
            "pmids": ["12345", "67890"],
            "tags": ["EGFR", "Monoclonal"],
        }
    ]


def test_executor_wraps_exceptions(monkeypatch):
    config = PipelineConfig()

    class ErroringSession:
        def __enter__(self):  # pragma: no cover - trivial
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
            return False

    class ErroringDriver:
        def session(self, *, timeout: float):
            return ErroringSession()

        def close(self):  # pragma: no cover - trivial
            pass

    monkeypatch.setattr(
        "pipeline.executor.GraphDatabase",
        type("_GraphDatabase", (), {"driver": staticmethod(lambda uri, auth: ErroringDriver())}),
    )

    executor = Neo4jExecutor(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        config=config,
    )

    with pytest.raises(PipelineError):
        executor.execute_read("MATCH (g:Gene) RETURN g")
