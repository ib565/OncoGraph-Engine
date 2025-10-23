"""Tests for Gemini-based instruction expander and Cypher generator."""

from __future__ import annotations

import pytest

from pipeline.gemini import (
    GeminiConfig,
    GeminiCypherGenerator,
    GeminiEnrichmentSummarizer,
    GeminiInstructionExpander,
    GeminiSummarizer,
    _format_rows,
    _strip_code_fence,
)
from pipeline.types import PipelineError


class StubResponse:
    def __init__(self, text: str | None):
        self.text = text


class StubModel:
    def __init__(self, responses: list[str | None]):
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        try:
            text = self._responses.pop(0)
        except IndexError:  # pragma: no cover - safety
            text = None
        return StubResponse(text)


class StubClient:
    def __init__(self, responses: list[str | None]):
        self.models = StubModel(responses)


def test_strip_code_fence():
    cypher = """```cypher
MATCH (g:Gene) RETURN g
```"""
    assert _strip_code_fence(cypher) == "MATCH (g:Gene) RETURN g"


def test_format_rows_handles_arrays():
    rows = [
        {
            "gene_symbol": "KRAS",
            "pmids": ["12345", "67890"],
            "tags": ["oncogene"],
        }
    ]

    formatted = _format_rows(rows)

    assert "gene_symbol: KRAS" in formatted
    assert "pmids: 12345, 67890" in formatted
    assert formatted.startswith("1. ")


def test_instruction_expander_uses_prompt(monkeypatch):
    stub_client = StubClient(["- Bullet 1\n- Bullet 2"])

    expander = GeminiInstructionExpander(config=GeminiConfig(), client=stub_client)
    result = expander.expand_instructions("Tell me about KRAS")

    assert result == "- Bullet 1\n- Bullet 2"
    call = stub_client.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert "Tell me about KRAS" in call["contents"][0]


def test_instruction_expander_errors_on_missing_text():
    expander = GeminiInstructionExpander(client=StubClient([None]))

    with pytest.raises(PipelineError):
        expander.expand_instructions("Question")


def test_cypher_generator_strips_markdown():
    generator = GeminiCypherGenerator(client=StubClient(["```MATCH (g) RETURN g```"]))

    cypher = generator.generate_cypher("Do things")

    assert cypher == "MATCH (g) RETURN g"


def test_cypher_generator_errors_on_empty_text():
    generator = GeminiCypherGenerator(client=StubClient([None]))

    with pytest.raises(PipelineError):
        generator.generate_cypher("Instructions")


def test_summarizer_runs_with_rows():
    stub_client = StubClient(["Answer with PMID 12345"])
    summarizer = GeminiSummarizer(client=stub_client)

    result = summarizer.summarize(
        "Question?",
        [{"therapy_name": "Cetuximab", "pmids": ["12345"]}],
    )

    assert result == "Answer with PMID 12345"
    call = stub_client.models.calls[0]
    assert "Cetuximab" in call["contents"][0]


def test_summarizer_handles_empty_rows():
    stub_client = StubClient(["No evidence found."])
    summarizer = GeminiSummarizer(client=stub_client)

    result = summarizer.summarize("Question?", [])

    assert result == "No evidence found."


def test_enrichment_summarizer_formats_results():
    """Test that enrichment summarizer formats results correctly."""
    import json

    stub_client = StubClient(
        [json.dumps({"summary": "The genes show DNA repair enrichment.", "followUpQuestions": []})]
    )
    summarizer = GeminiEnrichmentSummarizer(client=stub_client)

    gene_list = ["BRCA1", "BRCA2"]
    enrichment_results = [
        {
            "term": "DNA repair",
            "library": "GO_Biological_Process_2023",
            "p_value": 0.001,
            "adjusted_p_value": 0.01,
            "gene_count": 2,
            "genes": ["BRCA1", "BRCA2"],
            "description": "DNA repair pathway",
        }
    ]

    result = summarizer.summarize_enrichment(gene_list, enrichment_results)

    assert result.summary == "The genes show DNA repair enrichment."
    assert result.followUpQuestions == []
    call = stub_client.models.calls[0]
    assert "BRCA1, BRCA2" in call["contents"][0]
    assert "DNA repair" in call["contents"][0]
    assert "GO_Biological_Process_2023" in call["contents"][0]


def test_enrichment_summarizer_handles_empty_results():
    """Test enrichment summarizer with empty results."""
    import json

    stub_client = StubClient(
        [json.dumps({"summary": "No significant enrichments found.", "followUpQuestions": []})]
    )
    summarizer = GeminiEnrichmentSummarizer(client=stub_client)

    result = summarizer.summarize_enrichment(["BRCA1"], [])

    assert result.summary == "No significant enrichments found."
    assert result.followUpQuestions == []
    call = stub_client.models.calls[0]
    assert "No significant enrichments found" in call["contents"][0]


def test_enrichment_summarizer_limits_results():
    """Test that enrichment summarizer limits to top 10 results."""
    import json

    stub_client = StubClient([json.dumps({"summary": "Summary", "followUpQuestions": []})])
    summarizer = GeminiEnrichmentSummarizer(client=stub_client)

    # Create 15 mock results
    enrichment_results = [
        {
            "term": f"Pathway {i}",
            "library": "GO_Biological_Process_2023",
            "p_value": 0.001,
            "adjusted_p_value": 0.01,
            "gene_count": 2,
            "genes": ["BRCA1", "BRCA2"],
            "description": f"Description {i}",
        }
        for i in range(15)
    ]

    result = summarizer.summarize_enrichment(["BRCA1"], enrichment_results)

    assert result.summary == "Summary"
    assert result.followUpQuestions == []
    call = stub_client.models.calls[0]
    # Should only include first 10 results
    assert call["contents"][0].count("Pathway") == 10
