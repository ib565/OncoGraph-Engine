"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import dynamic from "next/dynamic";

// Dynamically import Plotly to avoid SSR issues
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

type EnrichmentResponse = {
  summary: string;
  valid_genes: string[];
  warnings: string[];
  enrichment_results: Array<{
    term: string;
    library: string;
    p_value: number;
    adjusted_p_value: number;
    odds_ratio?: number;
    gene_count: number;
    genes: string[];
    description: string;
  }>;
  plot_data: any;
  followUpQuestions: string[];
};

type GeneSetResponse = {
  genes: string[];
  description: string;
};

type PresetOption = {
  id: string;
  description: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL;

const PRESET_OPTIONS: PresetOption[] = [
  { id: "colorectal_therapy_genes", description: "Genes targeted by therapies for Colorectal Cancer" },
  { id: "lung_therapy_genes", description: "Genes targeted by therapies for Lung Cancer" },
  { id: "resistance_biomarker_genes", description: "All genes with known resistance biomarkers" },
  { id: "egfr_pathway_genes", description: "Genes targeted by EGFR pathway therapies" },
  { id: "top_biomarker_genes", description: "Top biomarker genes across all cancers" },
];

type HypothesisAnalyzerProps = {
  onNavigateToQuery?: (question: string) => void;
};

export default function HypothesisAnalyzer({ onNavigateToQuery }: HypothesisAnalyzerProps = {}) {
  const [genes, setGenes] = useState("");
  const [result, setResult] = useState<EnrichmentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingPreset, setIsLoadingPreset] = useState(false);

  async function loadPreset(presetId: string) {
    if (!API_URL) {
      setError("NEXT_PUBLIC_API_URL is not configured");
      return;
    }

    setIsLoadingPreset(true);
    setError(null);

    try {
      const response = await fetch(`${API_URL}/graph-gene-sets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset_id: presetId }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = (payload as any)?.detail;
        if (detail?.message) throw new Error(detail.message);
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = (await response.json()) as GeneSetResponse;
      const geneList = data.genes.join(", ");
      setGenes(geneList);
      
      // Automatically trigger analysis
      await analyzeGenes(geneList);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoadingPreset(false);
    }
  }

  async function analyzeGenes(input: string) {
    const trimmed = input.trim();

    if (!trimmed) {
      setGenes("");
      return;
    }

    setGenes(trimmed);

    if (!API_URL) {
      setError("NEXT_PUBLIC_API_URL is not configured");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${API_URL}/analyze/genes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ genes: trimmed }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = (payload as any)?.detail;
        if (detail?.message) throw new Error(detail.message);
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = (await response.json()) as EnrichmentResponse;
      setResult(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await analyzeGenes(genes);
  }

  return (
    <section className="card query-card">
      <div className="card-heading">
        <h2 className="card-title">Hypothesis Analyzer</h2>
        <p className="card-subtitle">
          Analyze gene lists for functional enrichment and biological themes.
          Enter gene symbols separated by commas or newlines.
        </p>
      </div>

      <form className="query-form" onSubmit={handleSubmit}>
        <div className="preset-section">
          <label htmlFor="preset-select" className="preset-label">
            Load preset gene list:
          </label>
          <select
            id="preset-select"
            className="preset-select"
            onChange={(event) => {
              if (event.target.value) {
                void loadPreset(event.target.value);
                event.target.value = ""; // Reset selection
              }
            }}
            disabled={isLoading || isLoadingPreset}
            value=""
          >
            <option value="">Choose a preset...</option>
            {PRESET_OPTIONS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.description}
              </option>
            ))}
          </select>
        </div>
        
        <textarea
          className="query-input"
          value={genes}
          onChange={(event) => setGenes(event.target.value)}
          placeholder="e.g. BRCA1, BRCA2, TP53, ATM, CHEK2"
          disabled={isLoading || isLoadingPreset}
          rows={4}
          style={{ resize: "vertical", minHeight: "100px" }}
        />
        <button
          type="submit"
          className="primary-button"
          disabled={isLoading || isLoadingPreset || !genes.trim()}
        >
          {isLoading ? "Analyzing..." : isLoadingPreset ? "Loading preset..." : "Analyze Genes"}
        </button>
      </form>


      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      {result && (
        <div className="result-overview">
          <div className="primary-column">
            {/* AI Summary */}
            <section className="card answer-card">
              <h3 className="section-title">Biological Summary</h3>
              <div className="answer-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.summary}</ReactMarkdown>
              </div>
            </section>

            {/* Follow-up Questions */}
            {result.followUpQuestions && result.followUpQuestions.length > 0 && (
              <section className="card">
                <h3 className="section-title">Suggested Next Steps</h3>
                <p className="section-subtitle">
                  Explore these questions using the Knowledge Graph Query tab:
                </p>
                <div className="followup-questions">
                  {result.followUpQuestions.map((question, index) => (
                    <button
                      key={index}
                      className="followup-question-button"
                      onClick={() => {
                        if (onNavigateToQuery) {
                          onNavigateToQuery(question);
                        }
                      }}
                      disabled={!onNavigateToQuery}
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </section>
            )}

            {/* Warnings */}
            {result.warnings.length > 0 && (
              <section className="card">
                <h3 className="section-title">Warnings</h3>
                <div className="alert" role="alert">
                  {result.warnings.map((warning, index) => (
                    <div key={index}>{warning}</div>
                  ))}
                </div>
              </section>
            )}

            {/* Dot Plot Visualization */}
            {result.plot_data && Object.keys(result.plot_data).length > 0 && (
              <section className="card graph-card">
                <header className="panel-header">
                  <h3 className="panel-title">Enrichment Dot Plot</h3>
                  <p className="panel-copy">
                    Interactive visualization of enriched pathways and processes.
                    Larger dots indicate more genes in the pathway.
                  </p>
                </header>
                <div className="graph-shell">
                  <Plot
                    data={result.plot_data.data || []}
                    layout={result.plot_data.layout || {}}
                    style={{ width: "100%", height: "600px" }}
                    config={{
                      displayModeBar: true,
                      displaylogo: false,
                      modeBarButtonsToRemove: ["pan2d", "lasso2d", "select2d"],
                    }}
                  />
                </div>
              </section>
            )}

            {/* Enrichment Results Table */}
            {result.enrichment_results.length > 0 && (
              <section className="card rows-card">
                <header className="panel-header">
                  <h3 className="panel-title">Enrichment Results</h3>
                  <p className="panel-copy">
                    Detailed results from functional enrichment analysis.
                    Results are sorted by statistical significance.
                  </p>
                </header>
                <div className="rows-scroll" role="list">
                  {result.enrichment_results.map((item, index) => (
                    <article className="row-card" key={`enrichment-${index}`} role="listitem">
                      <header className="row-heading">
                        {item.term} ({item.library})
                      </header>
                      <dl className="row-details">
                        <div className="row-item">
                          <dt className="row-key">P-value</dt>
                          <dd className="row-value">{item.p_value.toExponential(2)}</dd>
                        </div>
                        <div className="row-item">
                          <dt className="row-key">Adjusted P-value</dt>
                          <dd className="row-value">{item.adjusted_p_value.toExponential(2)}</dd>
                        </div>
                        <div className="row-item">
                          <dt className="row-key">Gene Count</dt>
                          <dd className="row-value">{item.gene_count}</dd>
                        </div>
                        {item.odds_ratio && (
                          <div className="row-item">
                            <dt className="row-key">Odds Ratio</dt>
                            <dd className="row-value">{item.odds_ratio.toFixed(2)}</dd>
                          </div>
                        )}
                        <div className="row-item">
                          <dt className="row-key">Genes</dt>
                          <dd className="row-value">
                            <div className="value-pills">
                              {item.genes.slice(0, 10).map((gene, geneIndex) => (
                                <span key={`${index}-${geneIndex}`} className="value-pill">
                                  {gene}
                                </span>
                              ))}
                              {item.genes.length > 10 && (
                                <span className="value-pill">
                                  +{item.genes.length - 10} more
                                </span>
                              )}
                            </div>
                          </dd>
                        </div>
                        {item.description && (
                          <div className="row-item">
                            <dt className="row-key">Description</dt>
                            <dd className="row-value">{item.description}</dd>
                          </div>
                        )}
                      </dl>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {/* Valid Genes Summary */}
            <section className="card">
              <h3 className="section-title">Analyzed Genes</h3>
              <div className="value-pills">
                {result.valid_genes.map((gene, index) => (
                  <span key={index} className="value-pill">
                    {gene}
                  </span>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}
