"""Tests for gene enrichment analysis functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.enrichment import EnrichmentResult, GeneEnrichmentAnalyzer
from pipeline.gemini import EnrichmentSummaryResponse, GeminiConfig, GeminiEnrichmentSummarizer


class TestEnrichmentResult:
    """Test the EnrichmentResult dataclass."""

    def test_enrichment_result_creation(self):
        """Test creating an EnrichmentResult instance."""
        result = EnrichmentResult(
            valid_genes=["BRCA1", "BRCA2"],
            invalid_genes=["INVALID"],
            enrichment_results=[{"term": "DNA repair", "p_value": 0.001}],
            plot_data={"data": [], "layout": {}},
        )

        assert result.valid_genes == ["BRCA1", "BRCA2"]
        assert result.invalid_genes == ["INVALID"]
        assert len(result.enrichment_results) == 1
        assert result.plot_data == {"data": [], "layout": {}}


class TestGeneEnrichmentAnalyzer:
    """Test the GeneEnrichmentAnalyzer class."""

    def test_initialization_without_dependencies(self):
        """Test that initialization fails without required dependencies."""
        with patch("pipeline.enrichment.mygene", None):
            with pytest.raises(ImportError, match="mygene package is required"):
                GeneEnrichmentAnalyzer()

        with patch("pipeline.enrichment.gp", None):
            with pytest.raises(ImportError, match="gseapy package is required"):
                GeneEnrichmentAnalyzer()

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_initialization_with_dependencies(self, mock_gp, mock_mygene):
        """Test successful initialization with dependencies."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()

        analyzer = GeneEnrichmentAnalyzer()

        assert analyzer.mg is not None
        assert analyzer.enrichr_libraries == [
            "GO_Biological_Process_2023",
            "KEGG_2021_Human",
            "Reactome_2022",
        ]

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_run_enrichment_with_custom_libraries(self, mock_gp, mock_mygene):
        """Test enrichment analysis with custom library selection."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()

        # Mock GSEAPy enrichr results
        mock_enr = MagicMock()
        mock_gp.enrichr.return_value = mock_enr
        mock_enr.results = {}  # Empty results for simplicity

        analyzer = GeneEnrichmentAnalyzer()
        custom_libraries = ["GO_Biological_Process_2023", "Reactome_2022"]
        results = analyzer.run_enrichment(["BRCA1", "BRCA2"], libraries=custom_libraries)

        # Verify that enrichr was called with custom libraries
        mock_gp.enrichr.assert_called_once()
        call_args = mock_gp.enrichr.call_args
        assert call_args[1]["gene_list"] == ["BRCA1", "BRCA2"]
        assert call_args[1]["gene_sets"] == custom_libraries
        assert call_args[1]["organism"] == "human"
        assert call_args[1]["cutoff"] == 0.05

        # With empty results, we should get empty list
        assert results == []

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_run_enrichment_with_empty_libraries(self, mock_gp, mock_mygene):
        """Test enrichment analysis with empty library list."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()

        analyzer = GeneEnrichmentAnalyzer()
        results = analyzer.run_enrichment(["BRCA1", "BRCA2"], libraries=[])

        # Should return empty list without calling enrichr
        assert results == []
        mock_gp.enrichr.assert_not_called()

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_analyze_with_custom_libraries(self, mock_gp, mock_mygene):
        """Test the complete analyze method with custom libraries."""
        mock_mg = MagicMock()
        mock_mygene.MyGeneInfo.return_value = mock_mg
        mock_mg.querymany.return_value = {"out": [{"query": "BRCA1", "symbol": "BRCA1"}]}

        # Mock enrichment results
        mock_enr = MagicMock()
        mock_gp.enrichr.return_value = mock_enr
        mock_enr.results = {}

        analyzer = GeneEnrichmentAnalyzer()
        custom_libraries = ["GO_Biological_Process_2023"]
        result = analyzer.analyze(["BRCA1"], libraries=custom_libraries)

        assert isinstance(result, EnrichmentResult)
        assert "BRCA1" in result.valid_genes
        assert result.invalid_genes == []
        assert isinstance(result.enrichment_results, list)
        assert isinstance(result.plot_data, dict)

        # Verify enrichr was called with custom libraries
        call_args = mock_gp.enrichr.call_args
        assert call_args[1]["gene_sets"] == custom_libraries

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_normalize_genes_empty_input(self, mock_gp, mock_mygene):
        """Test gene normalization with empty input."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()
        analyzer = GeneEnrichmentAnalyzer()

        valid, invalid = analyzer.normalize_genes([])

        assert valid == []
        assert invalid == []

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_normalize_genes_success(self, mock_gp, mock_mygene):
        """Test successful gene normalization."""
        mock_mg = MagicMock()
        mock_mygene.MyGeneInfo.return_value = mock_mg
        mock_mg.querymany.return_value = {
            "out": [
                {"query": "BRCA1", "symbol": "BRCA1"},
                {"query": "BRCA2", "symbol": "BRCA2"},
                {"query": "INVALID", "notfound": True},
            ]
        }

        analyzer = GeneEnrichmentAnalyzer()
        valid, invalid = analyzer.normalize_genes(["BRCA1", "BRCA2", "INVALID"])

        assert "BRCA1" in valid
        assert "BRCA2" in valid
        assert "INVALID" in invalid
        mock_mg.querymany.assert_called_once()

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_normalize_genes_exception_handling(self, mock_gp, mock_mygene):
        """Test gene normalization handles exceptions gracefully."""
        mock_mg = MagicMock()
        mock_mygene.MyGeneInfo.return_value = mock_mg
        mock_mg.querymany.side_effect = Exception("API error")

        analyzer = GeneEnrichmentAnalyzer()
        valid, invalid = analyzer.normalize_genes(["BRCA1", "BRCA2"])

        assert valid == []
        assert set(invalid) == {"BRCA1", "BRCA2"}

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_run_enrichment_empty_gene_list(self, mock_gp, mock_mygene):
        """Test enrichment analysis with empty gene list."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()
        analyzer = GeneEnrichmentAnalyzer()

        results = analyzer.run_enrichment([])

        assert results == []

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_run_enrichment_success(self, mock_gp, mock_mygene):
        """Test successful enrichment analysis."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()

        # Mock GSEAPy enrichr results - just test that it calls the function
        mock_enr = MagicMock()
        mock_gp.enrichr.return_value = mock_enr
        mock_enr.results = {}  # Empty results for simplicity

        analyzer = GeneEnrichmentAnalyzer()
        results = analyzer.run_enrichment(["BRCA1", "BRCA2"])

        # Verify that enrichr was called with correct parameters
        mock_gp.enrichr.assert_called_once()
        call_args = mock_gp.enrichr.call_args
        assert call_args[1]["gene_list"] == ["BRCA1", "BRCA2"]
        assert call_args[1]["organism"] == "human"
        assert call_args[1]["cutoff"] == 0.05

        # With empty results, we should get empty list
        assert results == []

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_create_plot_data_empty_results(self, mock_gp, mock_mygene):
        """Test plot data creation with empty results."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()
        analyzer = GeneEnrichmentAnalyzer()

        plot_data = analyzer.create_plot_data([])

        assert plot_data == {"data": [], "layout": {}}

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_create_plot_data_with_results(self, mock_gp, mock_mygene):
        """Test plot data creation with enrichment results."""
        mock_mygene.MyGeneInfo.return_value = MagicMock()
        analyzer = GeneEnrichmentAnalyzer()

        enrichment_results = [
            {
                "term": "DNA repair",
                "library": "GO_Biological_Process_2023",
                "adjusted_p_value": 0.01,
                "gene_count": 3,
                "description": "DNA repair pathway",
            }
        ]

        plot_data = analyzer.create_plot_data(enrichment_results)

        assert "data" in plot_data
        assert "layout" in plot_data
        assert len(plot_data["data"]) == 1  # One trace for the library

    @patch("pipeline.enrichment.mygene")
    @patch("pipeline.enrichment.gp")
    def test_analyze_integration(self, mock_gp, mock_mygene):
        """Test the complete analyze method integration."""
        mock_mg = MagicMock()
        mock_mygene.MyGeneInfo.return_value = mock_mg
        mock_mg.querymany.return_value = {"out": [{"query": "BRCA1", "symbol": "BRCA1"}]}

        # Mock enrichment results
        mock_enr = MagicMock()
        mock_gp.enrichr.return_value = mock_enr
        mock_enr.results = {}

        analyzer = GeneEnrichmentAnalyzer()
        result = analyzer.analyze(["BRCA1"])

        assert isinstance(result, EnrichmentResult)
        assert "BRCA1" in result.valid_genes
        assert result.invalid_genes == []
        assert isinstance(result.enrichment_results, list)
        assert isinstance(result.plot_data, dict)


class TestEnrichmentSummaryResponse:
    """Test the EnrichmentSummaryResponse Pydantic model."""

    def test_enrichment_summary_response_creation(self):
        """Test creating an EnrichmentSummaryResponse instance."""
        response = EnrichmentSummaryResponse(
            summary="This gene set shows enrichment in DNA repair pathways.",
            followUpQuestions=[
                "What therapies target BRCA1 in breast cancer?",
                "What resistance mechanisms are known for PARP inhibitors?",
            ],
        )

        assert response.summary == "This gene set shows enrichment in DNA repair pathways."
        assert len(response.followUpQuestions) == 2
        assert "BRCA1" in response.followUpQuestions[0]
        assert "PARP inhibitors" in response.followUpQuestions[1]

    def test_enrichment_summary_response_validation(self):
        """Test that validation works correctly."""
        # Valid response
        response = EnrichmentSummaryResponse(summary="Test summary", followUpQuestions=["Question 1", "Question 2"])
        assert response.summary == "Test summary"
        assert response.followUpQuestions == ["Question 1", "Question 2"]

        # Empty follow-up questions should be valid
        response = EnrichmentSummaryResponse(summary="Test summary", followUpQuestions=[])
        assert response.followUpQuestions == []


class TestGeminiEnrichmentSummarizer:
    """Test the GeminiEnrichmentSummarizer with structured output."""

    def test_initialization_without_dependencies(self):
        """Test that initialization fails without required dependencies."""
        with patch("pipeline.gemini.genai", None):
            with pytest.raises(Exception, match="google-genai package is required"):
                GeminiEnrichmentSummarizer()

    @patch("pipeline.gemini.genai")
    @patch("pipeline.gemini.genai_types")
    def test_summarize_enrichment_structured_output(self, mock_genai_types, mock_genai):
        """Test that summarize_enrichment returns structured output."""
        # Mock the Gemini client
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock the response
        mock_response = MagicMock()
        mock_response.text = '{"summary": "Test summary", "followUpQuestions": ["Question 1", "Question 2"]}'
        mock_client.models.generate_content.return_value = mock_response

        # Mock the config types
        mock_genai_types.GenerateContentConfig.return_value = MagicMock()

        config = GeminiConfig(api_key="test-key")
        summarizer = GeminiEnrichmentSummarizer(config=config)

        gene_list = ["BRCA1", "BRCA2"]
        enrichment_results = [
            {
                "term": "DNA repair",
                "library": "GO_Biological_Process_2023",
                "p_value": 0.001,
                "adjusted_p_value": 0.01,
                "gene_count": 5,
                "genes": ["BRCA1", "BRCA2", "ATM", "CHEK2", "TP53"],
                "description": "DNA repair pathway",
            }
        ]

        result = summarizer.summarize_enrichment(gene_list, enrichment_results)

        assert isinstance(result, EnrichmentSummaryResponse)
        assert result.summary == "Test summary"
        assert result.followUpQuestions == ["Question 1", "Question 2"]

    @patch("pipeline.gemini.genai")
    @patch("pipeline.gemini.genai_types")
    def test_summarize_enrichment_invalid_json(self, mock_genai_types, mock_genai):
        """Test error handling for invalid JSON response."""
        # Mock the Gemini client
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock invalid JSON response
        mock_response = MagicMock()
        mock_response.text = "Invalid JSON response"
        mock_client.models.generate_content.return_value = mock_response

        # Mock the config types
        mock_genai_types.GenerateContentConfig.return_value = MagicMock()

        config = GeminiConfig(api_key="test-key")
        summarizer = GeminiEnrichmentSummarizer(config=config)

        gene_list = ["BRCA1"]
        enrichment_results = []

        with pytest.raises(Exception, match="Failed to parse structured response"):
            summarizer.summarize_enrichment(gene_list, enrichment_results)
