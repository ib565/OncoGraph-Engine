"""Integration test wiring Gemini stubs, validator, executor, and query engine."""

from __future__ import annotations

from pipeline import (
    GeminiConfig,
    PipelineConfig,
    QueryEngine,
)
from pipeline.executor import Neo4jExecutor
from pipeline.gemini import (
    GeminiCypherGenerator,
    GeminiInstructionExpander,
    GeminiSummarizer,
)
from pipeline.types import QueryEngineResult
from pipeline.validator import RuleBasedValidator


class StaticGeminiClient:
    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[dict[str, object]] = []
        self._models = self._Models(self)

    class _Models:
        def __init__(self, parent: StaticGeminiClient) -> None:
            self._parent = parent

        def generate_content(
            self, *, model: str, contents: list[str], config=None
        ):  # pragma: no cover - simple
            prompt = contents[0]
            self._parent.calls.append(
                {
                    "model": model,
                    "prompt": prompt,
                    "config": config,
                }
            )
            text = None
            for key, value in self._parent.responses.items():
                if key in prompt:
                    text = value
                    break
            return type("_Response", (), {"text": text})

    @property
    def models(self) -> StaticGeminiClient._Models:  # pragma: no cover - simple property
        return self._models

    def __getattr__(self, item):  # pragma: no cover - fallback
        raise AttributeError(item)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass style hook unused
        pass

    def __init_subclass__(cls):  # pragma: no cover - not used
        pass


class DummyExecutor(Neo4jExecutor):
    def __post_init__(self) -> None:  # override to avoid real driver
        self._driver = None  # type: ignore[attr-defined]

    def execute_read(self, cypher: str):
        self.last_cypher = cypher
        return [
            {
                "gene_symbol": "KRAS",
                "therapy_name": "Cetuximab",
                "effect": "resistance",
                "pmids": ["12345"],
            }
        ]


def test_pipeline_with_gemini_stubs(monkeypatch):
    config = PipelineConfig()
    gemini_config = GeminiConfig()
    client = StaticGeminiClient(
        responses={
            "User question": "- Investigate KRAS and Cetuximab",
            "Instruction text": "MATCH (b:Biomarker)-[:AFFECTS_RESPONSE_TO]->(t:Therapy) RETURN b LIMIT 5",
            "Original question": "KRAS mutations confer resistance",
        }
    )

    monkeypatch.setattr(
        "pipeline.gemini.genai",
        type("_GenAI", (), {"Client": staticmethod(lambda **kwargs: client)}),
    )

    expander = GeminiInstructionExpander(config=gemini_config, client=client)
    generator = GeminiCypherGenerator(config=gemini_config, client=client)
    summarizer = GeminiSummarizer(config=gemini_config, client=client)
    validator = RuleBasedValidator(config=config)
    executor = DummyExecutor(
        uri="bolt://localhost", user="neo4j", password="password", config=config
    )

    engine = QueryEngine(
        config=config,
        expander=expander,
        generator=generator,
        validator=validator,
        executor=executor,
        summarizer=summarizer,
    )

    result: QueryEngineResult = engine.run("Do KRAS mutations resist Cetuximab?")

    assert result.answer
    assert "KRAS" in result.answer
    assert result.rows[0]["therapy_name"] == "Cetuximab"
    assert "MATCH" in result.cypher
