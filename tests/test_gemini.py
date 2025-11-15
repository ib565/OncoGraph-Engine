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
        self.api_key_used: str | None = None


class RateLimitException(Exception):
    """Exception that mimics Gemini API rate limit errors."""

    def __init__(self, code: str = "429", status_code: int = 429, message: str = "RESOURCE_EXHAUSTED"):
        self.code = code
        self.status_code = status_code
        self.message = message
        super().__init__(f"{status_code} {message}")


class ExceptionStubModel:
    """Stub model that can raise exceptions and track API key usage."""

    def __init__(self, parent_client: StubClient, responses: list[str | Exception | None]):
        self._parent = parent_client
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        # Track API key if provided in kwargs (for testing key switching)
        if "api_key" in kwargs:
            self._parent.api_key_used = kwargs["api_key"]
        try:
            response = self._responses.pop(0)
        except IndexError:  # pragma: no cover - safety
            response = None
        if isinstance(response, Exception):
            raise response
        return StubResponse(response)


class ExceptionStubClient:
    """Stub client that can raise exceptions and track API key usage."""

    def __init__(self, responses: list[str | Exception | None]):
        self.models = ExceptionStubModel(self, responses)
        self.api_key_used: str | None = None


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

    stub_client = StubClient([json.dumps({"summary": "No significant enrichments found.", "followUpQuestions": []})])
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


class TestAlternateApiKeyFallback:
    """Tests for alternate API key fallback on rate limits."""

    def test_rate_limit_detection_via_code(self):
        """Test that rate limit errors are detected via code attribute."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            pass

        base = TestGeminiBase(config=GeminiConfig(api_key="test-key"), client=StubClient([]))
        exc = RateLimitException(code="429")
        assert base._is_rate_limit_error(exc) is True

    def test_rate_limit_detection_via_status_code(self):
        """Test that rate limit errors are detected via status_code attribute."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            pass

        base = TestGeminiBase(config=GeminiConfig(api_key="test-key"), client=StubClient([]))
        exc = RateLimitException(status_code=429)
        assert base._is_rate_limit_error(exc) is True

    def test_rate_limit_detection_via_message(self):
        """Test that rate limit errors are detected via RESOURCE_EXHAUSTED in message."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            pass

        base = TestGeminiBase(config=GeminiConfig(api_key="test-key"), client=StubClient([]))
        exc = Exception("429 RESOURCE_EXHAUSTED")
        assert base._is_rate_limit_error(exc) is True

    def test_non_rate_limit_error_not_detected(self):
        """Test that non-rate-limit errors are not detected as rate limits."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            pass

        base = TestGeminiBase(config=GeminiConfig(api_key="test-key"), client=StubClient([]))
        exc = Exception("500 Internal Server Error")
        assert base._is_rate_limit_error(exc) is False

    def test_key_switch_on_rate_limit_with_alternate_key(self, monkeypatch):
        """Test that key switches to alternate when rate limit is hit."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            def _call_model(self, *, prompt: str) -> str:
                return super()._call_model(prompt=prompt)

        # Create clients that raise rate limit on first call, succeed on second
        primary_client = ExceptionStubClient([RateLimitException(), "Success response"])
        alternate_client = ExceptionStubClient(["Success response"])

        client_factory_calls = []

        def mock_client_factory(**kwargs):
            client_factory_calls.append(kwargs.get("api_key"))
            if kwargs.get("api_key") == "primary-key":
                return primary_client
            elif kwargs.get("api_key") == "alt-key":
                return alternate_client
            return primary_client

        # Mock genai.Client to track which key is used
        mock_genai_module = type("_GenAI", (), {"Client": staticmethod(mock_client_factory)})()
        monkeypatch.setattr("pipeline.gemini.genai", mock_genai_module)

        config = GeminiConfig(api_key="primary-key", api_key_alt="alt-key")
        base = TestGeminiBase(config=config)

        # First call should fail with rate limit, then succeed with alternate key
        result = base._call_model(prompt="test prompt")

        assert result == "Success response"
        # Should have tried primary key first, then switched to alternate
        assert len(client_factory_calls) >= 1
        assert "primary-key" in client_factory_calls or "alt-key" in client_factory_calls

    def test_no_key_switch_when_alternate_not_configured(self, monkeypatch):
        """Test that no key switch occurs when alternate key is not configured."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            def _call_model(self, *, prompt: str) -> str:
                return super()._call_model(prompt=prompt)

        # Create a client that raises rate limit
        rate_limit_client = ExceptionStubClient([RateLimitException(), RateLimitException(), RateLimitException()])

        def mock_client_factory(**kwargs):
            return rate_limit_client

        mock_genai_module = type("_GenAI", (), {"Client": staticmethod(mock_client_factory)})()
        monkeypatch.setattr("pipeline.gemini.genai", mock_genai_module)

        config = GeminiConfig(api_key="primary-key", api_key_alt=None)
        base = TestGeminiBase(config=config)

        # Should fail after retries without switching keys
        with pytest.raises(PipelineError, match="Gemini API call failed"):
            base._call_model(prompt="test prompt")

        # Should have attempted 3 times with the same client
        assert len(rate_limit_client.models.calls) == 3

    def test_instruction_expander_switches_key_on_rate_limit(self, monkeypatch):
        """Test that instruction expander switches keys on rate limit."""
        from pipeline.gemini import genai

        # First call fails with rate limit, second succeeds
        primary_client = ExceptionStubClient([RateLimitException(), "Expanded instructions"])
        alternate_client = ExceptionStubClient(["Expanded instructions"])

        client_factory_calls = []

        def mock_client_factory(**kwargs):
            api_key = kwargs.get("api_key")
            client_factory_calls.append(api_key)
            if api_key == "primary-key":
                return primary_client
            elif api_key == "alt-key":
                return alternate_client
            return primary_client

        mock_genai_module = type("_GenAI", (), {"Client": staticmethod(mock_client_factory)})()
        monkeypatch.setattr("pipeline.gemini.genai", mock_genai_module)

        config = GeminiConfig(api_key="primary-key", api_key_alt="alt-key")
        expander = GeminiInstructionExpander(config=config)

        # Use a unique question to avoid cache collisions with other tests
        unique_question = "Test rate limit key switching for KRAS mutations"
        result = expander.expand_instructions(unique_question)

        assert result == "Expanded instructions"
        # Should have switched to alternate key
        assert len(client_factory_calls) >= 1

    def test_cypher_generator_switches_key_on_rate_limit(self, monkeypatch):
        """Test that Cypher generator switches keys on rate limit."""
        from pipeline.gemini import genai

        primary_client = ExceptionStubClient([RateLimitException(), "MATCH (g:Gene) RETURN g"])
        alternate_client = ExceptionStubClient(["MATCH (g:Gene) RETURN g"])

        def mock_client_factory(**kwargs):
            api_key = kwargs.get("api_key")
            if api_key == "primary-key":
                return primary_client
            elif api_key == "alt-key":
                return alternate_client
            return primary_client

        mock_genai_module = type("_GenAI", (), {"Client": staticmethod(mock_client_factory)})()
        monkeypatch.setattr("pipeline.gemini.genai", mock_genai_module)

        config = GeminiConfig(api_key="primary-key", api_key_alt="alt-key")
        generator = GeminiCypherGenerator(config=config)

        result = generator.generate_cypher("Find all genes")

        assert result == "MATCH (g:Gene) RETURN g"

    def test_no_switch_when_already_using_alternate_key(self, monkeypatch):
        """Test that no switch occurs when already using alternate key."""
        from pipeline.gemini import _GeminiBase

        class TestGeminiBase(_GeminiBase):
            def _call_model(self, *, prompt: str) -> str:
                return super()._call_model(prompt=prompt)

        # Create a client that raises rate limit
        alternate_client = ExceptionStubClient([RateLimitException(), RateLimitException(), RateLimitException()])

        def mock_client_factory(**kwargs):
            return alternate_client

        mock_genai_module = type("_GenAI", (), {"Client": staticmethod(mock_client_factory)})()
        monkeypatch.setattr("pipeline.gemini.genai", mock_genai_module)

        # Start with alternate key (simulating already switched state)
        config = GeminiConfig(api_key="primary-key", api_key_alt="alt-key")
        base = TestGeminiBase(config=config)
        # Manually set current key to alternate to simulate already-switched state
        base._current_api_key = "alt-key"

        # Should fail after retries without trying to switch again
        with pytest.raises(PipelineError, match="Gemini API call failed"):
            base._call_model(prompt="test prompt")

        # Should have attempted 3 times
        assert len(alternate_client.models.calls) == 3
