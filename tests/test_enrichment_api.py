"""Tests for the enrichment API endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import main
from pipeline.enrichment import EnrichmentResult
from pipeline.gemini import EnrichmentSummaryResponse


class StubEnrichmentAnalyzer:
    """Stub analyzer for testing."""

    def __init__(self, result: EnrichmentResult):
        self._result = result

    def analyze(self, gene_symbols: list[str]) -> EnrichmentResult:
        return self._result


class StubEnrichmentSummarizer:
    """Stub summarizer for testing."""

    def __init__(self, summary: str, follow_up_questions: list[str] | None = None):
        self._summary = summary
        self._follow_up_questions = follow_up_questions or []

    def summarize_enrichment(
        self, gene_list: list[str], enrichment_results: list[dict]
    ) -> EnrichmentSummaryResponse:
        return EnrichmentSummaryResponse(
            summary=self._summary, followUpQuestions=self._follow_up_questions
        )


@pytest.fixture
def app_client() -> TestClient:
    """Create test client with dependency overrides."""
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


def test_analyze_genes_success(app_client: TestClient) -> None:
    """Test successful gene analysis endpoint."""
    # Setup mock result
    mock_result = EnrichmentResult(
        valid_genes=["BRCA1", "BRCA2"],
        invalid_genes=["INVALID"],
        enrichment_results=[
            {
                "term": "DNA repair",
                "library": "GO_Biological_Process_2023",
                "p_value": 0.001,
                "adjusted_p_value": 0.01,
                "gene_count": 2,
                "genes": ["BRCA1", "BRCA2"],
                "description": "DNA repair pathway",
            }
        ],
        plot_data={"data": [], "layout": {}},
    )

    # Override dependencies
    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: StubEnrichmentAnalyzer(
        mock_result
    )
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Test summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "BRCA1, BRCA2, INVALID"})

    assert response.status_code == 200
    payload = response.json()

    assert payload["summary"] == "Test summary"
    assert payload["valid_genes"] == ["BRCA1", "BRCA2"]
    assert payload["warnings"] == ["Invalid gene symbols (excluded from analysis): INVALID"]
    assert len(payload["enrichment_results"]) == 1
    assert payload["enrichment_results"][0]["term"] == "DNA repair"
    assert payload["plot_data"] == {"data": [], "layout": {}}
    assert payload["followUpQuestions"] == []


def test_analyze_genes_empty_input(app_client: TestClient) -> None:
    """Test gene analysis with empty input."""
    response = app_client.post("/analyze/genes", json={"genes": ""})

    # Empty string fails Pydantic validation (min_length=1)
    assert response.status_code == 422
    payload = response.json()
    assert "detail" in payload


def test_analyze_genes_whitespace_only(app_client: TestClient) -> None:
    """Test gene analysis with whitespace-only input."""
    response = app_client.post("/analyze/genes", json={"genes": "   ,  ,  "})

    assert response.status_code == 400
    payload = response.json()
    assert "No valid gene symbols provided" in payload["detail"]


def test_analyze_genes_parses_comma_separated(app_client: TestClient) -> None:
    """Test that comma-separated genes are parsed correctly."""
    mock_result = EnrichmentResult(
        valid_genes=["BRCA1", "BRCA2"],
        invalid_genes=[],
        enrichment_results=[],
        plot_data={"data": [], "layout": {}},
    )

    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: StubEnrichmentAnalyzer(
        mock_result
    )
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "BRCA1, BRCA2"})

    assert response.status_code == 200


def test_analyze_genes_parses_newline_separated(app_client: TestClient) -> None:
    """Test that newline-separated genes are parsed correctly."""
    mock_result = EnrichmentResult(
        valid_genes=["BRCA1", "BRCA2"],
        invalid_genes=[],
        enrichment_results=[],
        plot_data={"data": [], "layout": {}},
    )

    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: StubEnrichmentAnalyzer(
        mock_result
    )
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "BRCA1\nBRCA2"})

    assert response.status_code == 200


def test_analyze_genes_parses_mixed_separators(app_client: TestClient) -> None:
    """Test that mixed separators are parsed correctly."""
    mock_result = EnrichmentResult(
        valid_genes=["BRCA1", "BRCA2", "TP53"],
        invalid_genes=[],
        enrichment_results=[],
        plot_data={"data": [], "layout": {}},
    )

    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: StubEnrichmentAnalyzer(
        mock_result
    )
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "BRCA1, BRCA2\nTP53"})

    assert response.status_code == 200


def test_analyze_genes_no_valid_genes_warning(app_client: TestClient) -> None:
    """Test warning when no valid genes are found."""
    mock_result = EnrichmentResult(
        valid_genes=[],
        invalid_genes=["INVALID1", "INVALID2"],
        enrichment_results=[],
        plot_data={"data": [], "layout": {}},
    )

    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: StubEnrichmentAnalyzer(
        mock_result
    )
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "INVALID1, INVALID2"})

    assert response.status_code == 200
    payload = response.json()

    assert "No valid gene symbols found for analysis" in payload["warnings"]
    assert (
        "Invalid gene symbols (excluded from analysis): INVALID1, INVALID2" in payload["warnings"]
    )


def test_analyze_genes_analyzer_exception(app_client: TestClient) -> None:
    """Test handling of analyzer exceptions."""

    class ErrorAnalyzer:
        def analyze(self, gene_symbols: list[str]) -> EnrichmentResult:
            raise Exception("Analysis failed")

    main.app.dependency_overrides[main.get_enrichment_analyzer] = lambda: ErrorAnalyzer()
    main.app.dependency_overrides[main.get_enrichment_summarizer] = (
        lambda: StubEnrichmentSummarizer("Summary")
    )

    response = app_client.post("/analyze/genes", json={"genes": "BRCA1"})

    assert response.status_code == 500
    payload = response.json()
    assert "Analysis failed" in payload["detail"]


def test_analyze_genes_missing_genes_field(app_client: TestClient) -> None:
    """Test validation error when genes field is missing."""
    response = app_client.post("/analyze/genes", json={})

    assert response.status_code == 422  # Validation error
