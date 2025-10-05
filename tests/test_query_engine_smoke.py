"""Smoke test for the QueryEngine with stubbed pipeline components."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline import PipelineConfig, QueryEngine


@dataclass
class StubExpander:
    response: str

    def expand_instructions(self, question: str) -> str:
        assert question
        return self.response


@dataclass
class StubGenerator:
    response: str

    def generate_cypher(self, instructions: str) -> str:
        assert instructions
        return self.response


@dataclass
class StubValidator:
    prefix: str = "// validated\n"

    def validate_cypher(self, cypher: str) -> str:
        assert "MATCH" in cypher
        return f"{self.prefix}{cypher}"


@dataclass
class StubExecutor:
    rows: list[dict[str, object]]

    def execute_read(self, cypher: str) -> list[dict[str, object]]:
        assert cypher.startswith("// validated")
        return self.rows


@dataclass
class StubSummarizer:
    def summarize(self, question: str, rows: list[dict[str, object]]) -> str:
        return f"{question} -> {len(rows)} rows"


def test_query_engine_smoke():
    engine = QueryEngine(
        config=PipelineConfig(),
        expander=StubExpander(response="Find KRAS evidence"),
        generator=StubGenerator(response="MATCH (g:Gene {symbol: 'KRAS'}) RETURN g LIMIT 5"),
        validator=StubValidator(),
        executor=StubExecutor(rows=[{"gene_symbol": "KRAS"}]),
        summarizer=StubSummarizer(),
    )

    result = engine.run("What is KRAS?")

    assert result.cypher.startswith("// validated")
    assert result.rows == [{"gene_symbol": "KRAS"}]
    assert result.answer == "What is KRAS? -> 1 rows"
