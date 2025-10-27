"""Shared dataclasses and protocols for the Text-to-Cypher pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for running the query pipeline."""

    default_limit: int = 100
    max_limit: int = 200
    neo4j_timeout_seconds: float = 15.0
    neo4j_fetch_size: int = 100


@dataclass(frozen=True)
class QueryEngineResult:
    """Final response returned by the query engine."""

    answer: str
    cypher: str
    rows: list[dict[str, object]]


class InstructionExpander(Protocol):
    """Produces schema-aware guidance from the user question."""

    def expand_instructions(self, question: str) -> str:  # pragma: no cover - interface only
        ...


class CypherGenerator(Protocol):
    """Turns expanded instructions into a Cypher query string."""

    def generate_cypher(self, instructions: str) -> str:  # pragma: no cover - interface only
        ...


class CypherValidator(Protocol):
    """Validates and repairs Cypher queries for safety."""

    def validate_cypher(self, cypher: str) -> str:  # pragma: no cover - interface only
        ...


class CypherExecutor(Protocol):
    """Executes Cypher against Neo4j and returns rows as dictionaries."""

    def execute_read(self, cypher: str) -> list[dict[str, object]]:  # pragma: no cover - interface only
        ...


class Summarizer(Protocol):
    """Summarizes rows into a natural language answer."""

    def summarize(self, question: str, rows: list[dict[str, object]]) -> str:  # pragma: no cover - interface only
        ...


class PipelineError(RuntimeError):
    """Raised when a pipeline step fails."""

    def __init__(self, message: str, *, step: str | None = None):
        super().__init__(message)
        self.step = step


class TraceSink(Protocol):
    """Receives step-wise trace data emitted during pipeline execution."""

    def record(self, step: str, data: dict[str, object]) -> None:  # pragma: no cover - interface only
        ...


def with_context_trace(trace: TraceSink | None, context: dict[str, object]) -> TraceSink | None:
    """Utility: if a trace sink is provided, wrap it to inject a static context.

    Returns the wrapped sink, or None if trace is None.
    """
    if trace is None:
        return None
    # Local import to avoid a circular import at module load time
    from .trace import ContextTraceSink  # noqa: WPS433

    return ContextTraceSink(trace, context)
