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

    def execute_read(
        self, cypher: str
    ) -> list[dict[str, object]]:  # pragma: no cover - interface only
        ...


class Summarizer(Protocol):
    """Summarizes rows into a natural language answer."""

    def summarize(
        self, question: str, rows: list[dict[str, object]]
    ) -> str:  # pragma: no cover - interface only
        ...


class PipelineError(RuntimeError):
    """Raised when a pipeline step fails."""
