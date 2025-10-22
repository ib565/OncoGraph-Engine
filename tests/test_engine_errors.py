from __future__ import annotations

import pytest

from pipeline.engine import QueryEngine
from pipeline.types import PipelineConfig, PipelineError


class StubExpander:
    def expand_instructions(self, question: str) -> str:
        return "Instructions"


class FailingGenerator:
    def generate_cypher(self, instructions: str) -> str:  # type: ignore[override]
        raise RuntimeError("generator failed")


class DummyValidator:
    def validate_cypher(self, cypher: str) -> str:
        return cypher


class DummyExecutor:
    def execute_read(self, cypher: str) -> list[dict[str, object]]:
        return []


class DummySummarizer:
    def summarize(self, question: str, rows: list[dict[str, object]]) -> str:
        return "summary"


def test_query_engine_wraps_generator_failure() -> None:
    engine = QueryEngine(
        config=PipelineConfig(),
        expander=StubExpander(),
        generator=FailingGenerator(),
        validator=DummyValidator(),
        executor=DummyExecutor(),
        summarizer=DummySummarizer(),
    )

    with pytest.raises(PipelineError) as excinfo:
        engine.run("Question")

    error = excinfo.value
    assert error.step == "generate_cypher"
    assert "generator failed" in str(error)
