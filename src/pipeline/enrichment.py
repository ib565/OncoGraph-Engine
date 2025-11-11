"""Gene enrichment analysis using MyGene and GSEAPy."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from .utils import get_enrichment_cache, make_cache_key

try:  # pragma: no cover - optional dependencies
    import gseapy as gp
    import mygene
except ImportError:  # pragma: no cover - handled lazily
    gp = None  # type: ignore
    mygene = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentResult:
    """Structured enrichment analysis results."""

    valid_genes: list[str]
    invalid_genes: list[str]
    enrichment_results: list[dict[str, Any]]
    plot_data: dict[str, Any]


class GeneEnrichmentAnalyzer:
    """Analyzes gene lists for functional enrichment."""

    def __init__(self, trace=None, cache=None) -> None:
        """Initialize the analyzer with required dependencies."""
        if mygene is None:
            raise ImportError("mygene package is required for gene enrichment analysis")
        if gp is None:
            raise ImportError("gseapy package is required for gene enrichment analysis")

        self.mg = mygene.MyGeneInfo()
        self.enrichr_libraries = ["GO_Biological_Process_2023", "KEGG_2021_Human", "Reactome_2022"]
        self.trace = trace
        self._cache = cache or get_enrichment_cache()

    def _trace(self, step: str, data: dict[str, object]) -> None:
        """Log trace event if trace sink is available."""
        if self.trace is not None:
            try:
                self.trace.record(step, data)
            except Exception:
                pass

    def normalize_genes(self, gene_symbols: list[str]) -> tuple[list[str], list[str]]:
        """Normalize gene symbols and separate valid from invalid genes.

        Args:
            gene_symbols: List of gene symbols to normalize

        Returns:
            Tuple of (valid_genes, invalid_genes)
        """
        if not gene_symbols:
            return [], []

        # Clean and deduplicate input genes
        cleaned_genes = list(set(gene.strip().upper() for gene in gene_symbols if gene.strip()))

        if not cleaned_genes:
            return [], []

        # Check cache first
        cache_key = make_cache_key("normalize_genes", sorted(cleaned_genes))
        cached_result = self._cache.get(cache_key)
        if cached_result is not None:
            # Log cache hit
            if self.trace:
                self._trace("cache_hit", {"cache_key": cache_key, "operation": "normalize_genes"})
            return cached_result

        try:
            # Query MyGene for gene information
            self._trace(
                "mygene_query",
                {
                    "input_genes_count": len(cleaned_genes),
                    "input_genes_preview": (cleaned_genes[:10] if len(cleaned_genes) > 10 else cleaned_genes),
                },
            )

            query_result = self.mg.querymany(
                cleaned_genes,
                scopes="symbol,alias",
                fields="symbol,name",
                species="human",
                returnall=True,
            )

            # Process results
            valid_genes = []
            invalid_genes = []

            # Track which input genes were found
            found_symbols = set()

            for hit in query_result["out"]:
                if "symbol" in hit and hit["symbol"]:
                    valid_genes.append(hit["symbol"])
                    found_symbols.add(hit["query"].upper())

            # Find invalid genes (not found in MyGene)
            invalid_genes = [gene for gene in cleaned_genes if gene not in found_symbols]

            # Remove duplicates while preserving order
            valid_genes = list(dict.fromkeys(valid_genes))

            result = (valid_genes, invalid_genes)
            
            # Cache the result
            self._cache.set(cache_key, result)
            # Log cache set
            if self.trace:
                self._trace("cache_set", {"cache_key": cache_key, "operation": "normalize_genes"})

            # Log normalization results
            self._trace(
                "mygene_results",
                {
                    "valid_genes_count": len(valid_genes),
                    "invalid_genes_count": len(invalid_genes),
                    "valid_genes_preview": (valid_genes[:10] if len(valid_genes) > 10 else valid_genes),
                    "invalid_genes": (invalid_genes[:10] if len(invalid_genes) > 10 else invalid_genes),
                },
            )

            logger.info(
                f"Normalized {len(cleaned_genes)} input genes: {len(valid_genes)} valid, {len(invalid_genes)} invalid"
            )

            return result

        except Exception as e:
            import traceback

            logger.error(f"Gene normalization failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Fallback: treat all genes as invalid
            return [], cleaned_genes

    def run_enrichment(self, gene_list: list[str]) -> list[dict[str, Any]]:
        """Run enrichment analysis using GSEAPy.

        Args:
            gene_list: List of valid gene symbols

        Returns:
            List of enrichment results with metadata
        """
        if not gene_list:
            return []

        # Check cache first
        cache_key = make_cache_key("run_enrichment", sorted(gene_list), self.enrichr_libraries)
        cached_result = self._cache.get(cache_key)
        if cached_result is not None:
            # Log cache hit
            if self.trace:
                self._trace("cache_hit", {"cache_key": cache_key, "operation": "run_enrichment"})
            return cached_result

        try:
            # Log enrichment analysis start
            self._trace(
                "enrichr_start",
                {
                    "gene_list_count": len(gene_list),
                    "gene_list_preview": gene_list[:10] if len(gene_list) > 10 else gene_list,
                    "libraries": self.enrichr_libraries,
                },
            )

            # Run enrichr analysis
            enr = gp.enrichr(
                gene_list=gene_list,
                gene_sets=self.enrichr_libraries,
                organism="human",
                outdir=None,
                cutoff=0.05,
                format="json",
            )

            # GSEAPy returns results as a single DataFrame, not a dictionary
            if not hasattr(enr, "results") or enr.results.empty:
                logger.info("No enrichment results found")
                return []

            df = enr.results

            # Filter significant results
            significant = df[df["Adjusted P-value"] < 0.05].copy()

            if significant.empty:
                logger.info("No significant enrichment results found (p < 0.05)")
                return []

            # Add library information (extract from Gene_set column)
            significant["Library"] = significant["Gene_set"]
            significant["Gene_Count"] = significant["Genes"].apply(lambda x: len(x.split(";")) if pd.notna(x) else 0)

            # Convert to list of dicts
            all_results = []
            for _, row in significant.iterrows():
                all_results.append(
                    {
                        "term": row["Term"],
                        "library": row["Library"],
                        "p_value": float(row["P-value"]),
                        "adjusted_p_value": float(row["Adjusted P-value"]),
                        "odds_ratio": (float(row["Odds Ratio"]) if pd.notna(row["Odds Ratio"]) else None),
                        "gene_count": int(row["Gene_Count"]),
                        "genes": row["Genes"].split(";") if pd.notna(row["Genes"]) else [],
                        "description": row.get("Description", ""),
                    }
                )

            # Sort by adjusted p-value and limit to top results
            all_results.sort(key=lambda x: x["adjusted_p_value"])
            top_results = all_results[:15]

            # Log enrichment results
            self._trace(
                "enrichr_results",
                {
                    "total_significant_terms": len(all_results),
                    "top_results_count": len(top_results),
                    "top_terms_preview": [
                        {
                            "term": r["term"],
                            "library": r["library"],
                            "adjusted_p_value": r["adjusted_p_value"],
                            "gene_count": r["gene_count"],
                        }
                        for r in top_results[:5]
                    ],
                },
            )

            logger.info(f"Found {len(all_results)} significant enrichment terms, returning top {len(top_results)}")

            self._cache.set(cache_key, top_results)
            # Log cache set
            if self.trace:
                self._trace("cache_set", {"cache_key": cache_key, "operation": "run_enrichment"})
            return top_results

        except Exception as e:
            import traceback

            logger.error(f"Enrichment analysis failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def create_plot_data(self, enrichment_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Create Plotly-compatible data for dot plot visualization.

        Args:
            enrichment_results: List of enrichment results

        Returns:
            Plotly figure data as dictionary
        """
        if not enrichment_results:
            return {"data": [], "layout": {}}

        # Prepare data for plotting
        terms = []
        libraries = []
        p_values = []
        gene_counts = []
        descriptions = []

        for result in enrichment_results:
            terms.append(result["term"])
            libraries.append(result["library"])
            # Use -log10(adjusted_p_value) with epsilon clipping to avoid log(0)
            adj_pval = result["adjusted_p_value"]
            epsilon = 1e-300  # Very small epsilon to avoid log(0)
            clipped_pval = max(adj_pval, epsilon)
            p_values.append(-math.log10(clipped_pval))
            gene_counts.append(result["gene_count"])
            descriptions.append(result["description"])

        # Create scatter plot
        fig = go.Figure()

        # Color mapping for libraries
        library_colors = {
            "GO_Biological_Process_2023": "#1f77b4",
            "KEGG_2021_Human": "#ff7f0e",
            "Reactome_2022": "#2ca02c",
        }

        for lib in set(libraries):
            mask = [lib == l for l in libraries]  # noqa: E741
            fig.add_trace(
                go.Scatter(
                    x=[p for i, p in enumerate(p_values) if mask[i]],
                    y=[t for i, t in enumerate(terms) if mask[i]],
                    mode="markers",
                    marker=dict(
                        size=[gc for i, gc in enumerate(gene_counts) if mask[i]],
                        color=library_colors.get(lib, "#d62728"),
                        sizemode="diameter",
                        sizeref=2,
                        sizemin=4,
                        opacity=0.7,
                    ),
                    text=[d for i, d in enumerate(descriptions) if mask[i]],
                    hovertemplate="<b>%{y}</b><br>"
                    + "Library: "
                    + lib
                    + "<br>"
                    + "Adjusted P-value: %{customdata:.2e}<br>"
                    + "Gene Count: %{marker.size}<br>"
                    + "<extra></extra>",
                    customdata=[result["adjusted_p_value"] for i, result in enumerate(enrichment_results) if mask[i]],
                    name=lib.replace("_", " "),
                    showlegend=True,
                )
            )

        # Update layout
        fig.update_layout(
            title="Gene Enrichment Analysis",
            xaxis_title="-log10(Adjusted P-value)",
            yaxis_title="Enriched Terms",
            hovermode="closest",
            height=600,
            margin=dict(l=200, r=50, t=50, b=50),
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=1.01),
        )

        # Convert to JSON-serializable format
        return fig.to_dict()

    def analyze(self, gene_symbols: list[str]) -> EnrichmentResult:
        """Run complete enrichment analysis pipeline.

        Args:
            gene_symbols: List of gene symbols to analyze

        Returns:
            Structured enrichment analysis results
        """
        # Normalize genes
        valid_genes, invalid_genes = self.normalize_genes(gene_symbols)

        # Run enrichment analysis
        enrichment_results = self.run_enrichment(valid_genes)

        # Create plot data
        plot_data = self.create_plot_data(enrichment_results)

        return EnrichmentResult(
            valid_genes=valid_genes,
            invalid_genes=invalid_genes,
            enrichment_results=enrichment_results,
            plot_data=plot_data,
        )
