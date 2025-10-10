"""Neo4j executor adapter used by the query pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from neo4j import GraphDatabase, Session

from .types import PipelineConfig, PipelineError

ARRAY_FIELDS = {"pmids", "tags"}


def _normalize_array(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        items: Iterable[str] = (item.strip() for item in value.split(";"))
        return [item for item in items if item]
    return [value]


def _normalize_row(row: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if key in ARRAY_FIELDS:
            normalized[key] = _normalize_array(value)
        else:
            normalized[key] = value
    return normalized


@dataclass
class Neo4jExecutor:
    """Execute read-only Cypher queries with configured limits and timeouts."""

    uri: str
    user: str
    password: str
    config: PipelineConfig

    def __post_init__(self) -> None:
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def close(self) -> None:
        self._driver.close()

    def execute_read(self, cypher: str) -> list[dict[str, object]]:
        try:
            with self._driver.session() as session:
                return session.execute_read(self._run_query, cypher)
        except Exception as exc:  # pragma: no cover - defensive
            raise PipelineError(
                f"Neo4j execution failed: {type(exc).__name__}: {exc}", step="execute_read"
            ) from exc

    def _run_query(self, tx: Session, cypher: str) -> list[dict[str, object]]:
        result = tx.run(
            cypher,
            timeout=self.config.neo4j_timeout_seconds,
            fetch_size=self.config.neo4j_fetch_size,
        )
        rows = [record.data() for record in result]
        return [_normalize_row(row) for row in rows]
