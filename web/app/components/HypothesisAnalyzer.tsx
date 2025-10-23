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

type PartialEnrichmentResult = {
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
};

type SummaryResult = {
  summary: string;
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
  const [partialResult, setPartialResult] = useState<PartialEnrichmentResult | null>(null);
  const [summaryResult, setSummaryResult] = useState<SummaryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingPreset, setIsLoadingPreset] = useState(false);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);

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
      
      // Just populate the text area - user can modify and click analyze manually
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoadingPreset(false);
    }
  }

  async function analyzeGenesStreaming(input: string) {
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
    setPartialResult(null);
    setSummaryResult(null);
    setIsSummaryLoading(false);

    try {
      const url = `${API_URL}/analyze/genes/stream?genes=${encodeURIComponent(trimmed)}`;
      const eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        // Handle progress messages
        try {
          const data = JSON.parse(event.data);
          if (data.message) {
            // Progress message - could be used for UI feedback
            console.log("Progress:", data.message);
          }
        } catch (e) {
          // Ignore parsing errors for progress messages
        }
      };

      eventSource.onerror = (event) => {
        console.error("EventSource error:", event);
        
        // Only show error if we haven't received any results yet
        if (!partialResult && !summaryResult) {
          setError("Connection error occurred during analysis");
          setIsLoading(false);
          setIsSummaryLoading(false);
        }
        eventSource.close();
      };

      eventSource.addEventListener("partial", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          const data = JSON.parse(messageEvent.data) as PartialEnrichmentResult;
          setPartialResult(data);
          setIsSummaryLoading(true);
          setIsLoading(false); // Stop the main loading state
        } catch (err) {
          console.error("Failed to parse partial result:", err);
        }
      });

      eventSource.addEventListener("summary", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          const data = JSON.parse(messageEvent.data) as SummaryResult;
          setSummaryResult(data);
          setIsSummaryLoading(false);
          
          // Create complete result for backwards compatibility
          if (partialResult) {
            setResult({
              ...partialResult,
              ...data,
            });
          }
          
          // Close the EventSource since we have all results
          eventSource.close();
        } catch (err) {
          console.error("Failed to parse summary result:", err);
        }
      });

      eventSource.addEventListener("error", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          if (messageEvent.data) {
            const data = JSON.parse(messageEvent.data);
            const message = data.message || "An error occurred during analysis";
            setError(message);
          } else {
            setError("An error occurred during analysis");
          }
          setIsLoading(false);
          setIsSummaryLoading(false);
        } catch (err) {
          console.error("Failed to parse error result:", err);
          setError("An error occurred during analysis");
          setIsLoading(false);
          setIsSummaryLoading(false);
        }
        eventSource.close();
      });

      eventSource.addEventListener("progress", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          const data = JSON.parse(messageEvent.data);
          if (data.message) {
            console.log("Progress:", data.message);
          }
        } catch (e) {
          // Ignore parsing errors for progress messages
        }
      });

      // Close the event source when component unmounts or new analysis starts
      const cleanup = () => {
        eventSource.close();
      };

      // Store cleanup function for potential use
      (eventSource as any).cleanup = cleanup;

      // Set up timeout to close connection after reasonable time
      setTimeout(() => {
        if (eventSource.readyState !== EventSource.CLOSED) {
          eventSource.close();
          if (!partialResult && !summaryResult) {
            setError("Analysis timed out");
            setIsLoading(false);
            setIsSummaryLoading(false);
          }
        }
      }, 180000); // 3 minutes timeout

    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setIsLoading(false);
      setIsSummaryLoading(false);
    }
  }

  async function analyzeGenes(input: string) {
    // Use streaming by default
    await analyzeGenesStreaming(input);
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

      {(result || partialResult) && (
        <div className="result-overview">
          <div className="primary-column">
            {/* AI Summary */}
            <section className="card answer-card">
              <h3 className="section-title">Biological Summary</h3>
              <div className="answer-content">
                {summaryResult ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{summaryResult.summary}</ReactMarkdown>
                ) : isSummaryLoading ? (
                  <div className="loading-container">
                    <div className="spinner"></div>
                    <p>Generating AI summary...</p>
                  </div>
                ) : (
                  <p>Summary will appear here once analysis is complete.</p>
                )}
              </div>
            </section>

            {/* Follow-up Questions */}
            <section className="card">
              <h3 className="section-title">Suggested Next Steps</h3>
              <p className="section-subtitle">
                Explore these questions using the Knowledge Graph Query tab:
              </p>
              {summaryResult && summaryResult.followUpQuestions && summaryResult.followUpQuestions.length > 0 ? (
                <div className="followup-questions">
                  {summaryResult.followUpQuestions.map((question, index) => (
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
              ) : isSummaryLoading ? (
                <div className="loading-container">
                  <div className="spinner"></div>
                  <p>Generating follow-up questions...</p>
                </div>
              ) : (
                <p>Follow-up questions will appear here once analysis is complete.</p>
              )}
            </section>

            {/* Warnings */}
            {((partialResult && partialResult.warnings.length > 0) || (result && result.warnings.length > 0)) && (
              <section className="card">
                <h3 className="section-title">Warnings</h3>
                <div className="alert" role="alert">
                  {(partialResult?.warnings || result?.warnings || []).map((warning, index) => (
                    <div key={index}>{warning}</div>
                  ))}
                </div>
              </section>
            )}

            {/* Dot Plot Visualization */}
            {((partialResult && partialResult.plot_data && Object.keys(partialResult.plot_data).length > 0) || 
              (result && result.plot_data && Object.keys(result.plot_data).length > 0)) && (
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
                    data={(partialResult?.plot_data?.data || result?.plot_data?.data) || []}
                    layout={(partialResult?.plot_data?.layout || result?.plot_data?.layout) || {}}
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
            {((partialResult && partialResult.enrichment_results.length > 0) || 
              (result && result.enrichment_results.length > 0)) && (
              <section className="card rows-card">
                <header className="panel-header">
                  <h3 className="panel-title">Enrichment Results</h3>
                  <p className="panel-copy">
                    Detailed results from functional enrichment analysis.
                    Results are sorted by statistical significance.
                  </p>
                </header>
                <div className="rows-scroll" role="list">
                  {(partialResult?.enrichment_results || result?.enrichment_results || []).map((item, index) => (
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
                {(partialResult?.valid_genes || result?.valid_genes || []).map((gene, index) => (
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
