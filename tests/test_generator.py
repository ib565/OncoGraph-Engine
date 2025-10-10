"""Unit tests for the LLMBasedGenerator."""

from __future__ import annotations

import pytest

from pipeline.generator import LLMBasedGenerator
from pipeline.types import PipelineError


class StubClient:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate(self, prompt: str, *, temperature: float, max_tokens: int) -> str:
        # Record call for assertions
        self.calls.append(
            {"prompt_len": len(prompt), "temperature": temperature, "max_tokens": max_tokens}
        )
        return self.response


def test_llm_generator_basic_extraction():
    client = StubClient("MATCH (g:Gene {symbol: 'KRAS'}) RETURN g LIMIT 5")
    gen = LLMBasedGenerator(client=client)

    cypher = gen.generate_cypher("Find KRAS")

    assert cypher.startswith("MATCH ")
    assert "LIMIT" in cypher
    assert client.calls and client.calls[0]["temperature"] == 0.0


def test_llm_generator_extracts_from_code_fence():
    fenced = """```cypher
MATCH (g:Gene) RETURN g LIMIT 3
```"""
    client = StubClient(fenced)
    gen = LLMBasedGenerator(client=client)

    cypher = gen.generate_cypher("List genes")

    assert cypher == "MATCH (g:Gene) RETURN g LIMIT 3"


def test_llm_generator_rejects_empty_or_nonsense():
    client = StubClient("  ")
    gen = LLMBasedGenerator(client=client)

    with pytest.raises(PipelineError):
        gen.generate_cypher("Anything")

    client2 = StubClient("Hello there")
    gen2 = LLMBasedGenerator(client=client2)

    with pytest.raises(PipelineError):
        gen2.generate_cypher("Anything")
