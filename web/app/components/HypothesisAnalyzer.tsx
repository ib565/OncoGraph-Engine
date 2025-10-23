"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppContext, type EnrichmentResponse, type PartialEnrichmentResult, type SummaryResult } from "../contexts/AppContext";
import PlotlyChart from "./PlotlyChart";


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

// Library color mapping consistent with backend
const getLibraryColor = (library: string): string => {
  const libraryColors: Record<string, string> = {
    "GO_Biological_Process_2023": "#1f77b4",
    "KEGG_2021_Human": "#ff7f0e", 
    "Reactome_2022": "#2ca02c",
  };
  return libraryColors[library] || "#d62728";
};

export default function HypothesisAnalyzer({ onNavigateToQuery }: HypothesisAnalyzerProps = {}) {
  const { hypothesisState, setHypothesisState } = useAppContext();
  const { genes, result, partialResult, summaryResult, error, isLoading, isLoadingPreset, isSummaryLoading } = hypothesisState;
  
  // State for dot plot drawer
  const [selectedTerm, setSelectedTerm] = useState<{
    term: string;
    library: string;
    genes: string[];
  } | null>(null);

  async function loadPreset(presetId: string) {
    if (!API_URL) {
      setHypothesisState({ error: "NEXT_PUBLIC_API_URL is not configured" });
      return;
    }

    setHypothesisState({ 
      isLoadingPreset: true,
      error: null 
    });

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
      setHypothesisState({ genes: geneList });
      
      // Just populate the text area - user can modify and click analyze manually
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setHypothesisState({ error: message });
    } finally {
      setHypothesisState({ isLoadingPreset: false });
    }
  }

  async function analyzeGenesStreaming(input: string) {
    const trimmed = input.trim();

    if (!trimmed) {
      setHypothesisState({ genes: "" });
      return;
    }

    setHypothesisState({ genes: trimmed });

    if (!API_URL) {
      setHypothesisState({ error: "NEXT_PUBLIC_API_URL is not configured" });
      return;
    }

    setHypothesisState({
      isLoading: true,
      error: null,
      result: null,
      partialResult: null,
      summaryResult: null,
      isSummaryLoading: false
    });

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
          setHypothesisState({ 
            error: "Connection error occurred during analysis",
            isLoading: false,
            isSummaryLoading: false
          });
        }
        eventSource.close();
      };

      eventSource.addEventListener("partial", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          const data = JSON.parse(messageEvent.data) as PartialEnrichmentResult;
          setHypothesisState({ 
            partialResult: data,
            isSummaryLoading: true,
            isLoading: false
          });
        } catch (err) {
          console.error("Failed to parse partial result:", err);
        }
      });

      eventSource.addEventListener("summary", (event) => {
        try {
          const messageEvent = event as MessageEvent;
          const data = JSON.parse(messageEvent.data) as SummaryResult;
          
          // Ensure data has the correct structure
          const summaryResult: SummaryResult = {
            summary: data.summary || "",
            followUpQuestions: data.followUpQuestions || []
          };
          
          setHypothesisState({ 
            summaryResult: summaryResult,
            isSummaryLoading: false
          });
          
          // Create complete result for backwards compatibility
          if (partialResult) {
            setHypothesisState({
              result: {
                ...partialResult,
                summary: summaryResult.summary,
                followUpQuestions: summaryResult.followUpQuestions,
              }
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
            setHypothesisState({ 
              error: message,
              isLoading: false,
              isSummaryLoading: false
            });
          } else {
            setHypothesisState({ 
              error: "An error occurred during analysis",
              isLoading: false,
              isSummaryLoading: false
            });
          }
        } catch (err) {
          console.error("Failed to parse error result:", err);
          setHypothesisState({ 
            error: "An error occurred during analysis",
            isLoading: false,
            isSummaryLoading: false
          });
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
            setHypothesisState({ 
              error: "Analysis timed out",
              isLoading: false,
              isSummaryLoading: false
            });
          }
        }
      }, 180000); // 3 minutes timeout

    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setHypothesisState({ 
        error: message,
        isLoading: false,
        isSummaryLoading: false
      });
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
    <div className="bench-panel">
      <div className="panel-header">
        <h3 className="panel-title">Hypothesis Analyzer</h3>
      </div>
      <div className="panel-content">
        <div className="card-heading">
          <h2 className="card-title">Analyze Gene Lists</h2>
          <p className="card-subtitle">
            Analyze gene lists for functional enrichment and biological themes.
            Enter gene symbols separated by commas or newlines.
          </p>
        </div>

      {/* Row 1: Preset Selection | Gene Input */}
      <div className="layout-row">
        <div className="layout-column preset-column">
          <div className="card">
            <header className="panel-header">
              <h3 className="panel-title">Preset Gene Lists</h3>
            </header>
            <div className="card-content">
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
            </div>
          </div>
        </div>
        
        <div className="layout-column gene-input-column">
          <div className="card">
            <header className="panel-header">
              <h3 className="panel-title">Gene Input</h3>
            </header>
            <div className="card-content">
              <form className="query-form" onSubmit={handleSubmit}>
                <textarea
                  className="query-input"
                  value={genes}
                  onChange={(event) => setHypothesisState({ genes: event.target.value })}
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
                  {isLoading ? (
                    <>
                      <div className="button-spinner" style={{
                        display: "inline-block",
                        width: "16px",
                        height: "16px",
                        border: "2px solid #ffffff",
                        borderTop: "2px solid transparent",
                        borderRadius: "50%",
                        animation: "spin 1s linear infinite",
                        marginRight: "8px"
                      }}></div>
                      Analyzing...
                    </>
                  ) : isLoadingPreset ? (
                    <>
                      <div className="button-spinner" style={{
                        display: "inline-block",
                        width: "16px",
                        height: "16px",
                        border: "2px solid #ffffff",
                        borderTop: "2px solid transparent",
                        borderRadius: "50%",
                        animation: "spin 1s linear infinite",
                        marginRight: "8px"
                      }}></div>
                      Loading preset...
                    </>
                  ) : (
                    "Analyze Genes"
                  )}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>


      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      {(result || partialResult) && (
        <>
          {/* AI Summary - Full Width */}
          <div className="layout-row">
            <div className="layout-column full-width">
              <div className="card answer-card">
                <header className="panel-header">
                  <h3 className="panel-title">Biological Summary</h3>
                </header>
                <div className="card-content">
                  <div className="answer-content">
                    {summaryResult && typeof summaryResult === 'object' && 'summary' in summaryResult ? (
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
                </div>
              </div>
            </div>
          </div>

          {/* Follow-up Questions - Full Width */}
          <div className="layout-row">
            <div className="layout-column full-width">
              <div className="card">
                <header className="panel-header">
                  <h3 className="panel-title">Suggested Next Steps</h3>
                  <p className="panel-copy">
                    Explore these questions using the Knowledge Graph Query tab:
                  </p>
                </header>
                <div className="card-content">
                  {summaryResult && typeof summaryResult === 'object' && 'followUpQuestions' in summaryResult && summaryResult.followUpQuestions && summaryResult.followUpQuestions.length > 0 ? (
                    <div className="followup-questions">
                      {summaryResult.followUpQuestions.map((question, index) => (
                        <button
                          key={index}
                          className="followup-question-button"
                          onClick={() => {
                            if (onNavigateToQuery) {
                              onNavigateToQuery(question);
                            } else {
                              // Navigate to Graph Q&A with the question using Next.js router
                              window.location.href = `/?q=${encodeURIComponent(question)}`;
                            }
                          }}
                          disabled={false}
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
                </div>
              </div>
            </div>
          </div>

          {/* Dot Plot Visualization - Full Width */}
          {((partialResult && partialResult.plot_data && Object.keys(partialResult.plot_data).length > 0) || 
            (result && result.plot_data && Object.keys(result.plot_data).length > 0)) && (
            <div className="layout-row">
              <div className="layout-column full-width">
                <div className="card graph-card">
                  <header className="panel-header">
                    <h3 className="panel-title">Enrichment Dot Plot</h3>
                    <p className="panel-copy">
                      Interactive visualization of enriched pathways and processes.
                      Larger dots indicate more genes in the pathway.
                    </p>
                  </header>
                  <div className="card-content">
                    <div className="graph-shell">
                      <PlotlyChart
                        data={(partialResult?.plot_data?.data || result?.plot_data?.data) || []}
                        layout={(partialResult?.plot_data?.layout || result?.plot_data?.layout) || {}}
                        onClick={(event) => {
                          if (event.points && event.points.length > 0) {
                            const point = event.points[0];
                            const term = point.y;
                            const library = point.data.name?.replace(/ /g, "_") || "";
                            
                            // Find the enrichment result for this term
                            const enrichmentResults = partialResult?.enrichment_results || result?.enrichment_results || [];
                            const matchingResult = enrichmentResults.find(
                              (item: any) => item.term === term && item.library === library
                            );
                            
                            if (matchingResult) {
                              setSelectedTerm({
                                term: matchingResult.term,
                                library: matchingResult.library,
                                genes: matchingResult.genes || []
                              });
                            }
                          }
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Enrichment Results and Analyzed Genes - Split Row */}
          <div className="layout-row">
            {/* Enrichment Results Column */}
            {((partialResult && partialResult.enrichment_results.length > 0) || 
              (result && result.enrichment_results.length > 0)) ? (
              <div className="layout-column enrichment-column">
                <div className="card rows-card">
                  <header className="panel-header">
                    <h3 className="panel-title">Enrichment Results</h3>
                    <p className="panel-copy">
                      Detailed results from functional enrichment analysis.
                      Results are sorted by statistical significance.
                    </p>
                    {/* Gene count chips */}
                    <div className="gene-count-chips" style={{ marginTop: "8px" }}>
                      <span 
                        className="gene-count-chip" 
                        title="Symbols normalized with mygene.info (Human)."
                        style={{ 
                          display: "inline-block", 
                          padding: "4px 8px", 
                          marginRight: "8px", 
                          backgroundColor: "#e3f2fd", 
                          color: "#1976d2", 
                          borderRadius: "12px", 
                          fontSize: "12px",
                          cursor: "help"
                        }}
                      >
                        Used genes: {(partialResult?.valid_genes?.length || result?.valid_genes?.length) || 0}
                      </span>
                      <span 
                        className="gene-count-chip" 
                        title="Symbols normalized with mygene.info (Human)."
                        style={{ 
                          display: "inline-block", 
                          padding: "4px 8px", 
                          backgroundColor: "#fff3e0", 
                          color: "#f57c00", 
                          borderRadius: "12px", 
                          fontSize: "12px",
                          cursor: "help"
                        }}
                      >
                        Unrecognized: {(partialResult?.invalid_genes?.length || result?.invalid_genes?.length) || 0}
                      </span>
                    </div>
                  </header>
                  <div className="card-content">
                    <div className="enrichment-scroll" role="list">
                      {(partialResult?.enrichment_results || result?.enrichment_results || []).map((item, index) => (
                        <article className="row-card" key={`enrichment-${index}`} role="listitem">
                          <header className="row-heading">
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <span>{item.term}</span>
                              <span 
                                className="library-pill"
                                style={{
                                  padding: "2px 6px",
                                  borderRadius: "8px",
                                  fontSize: "10px",
                                  fontWeight: "500",
                                  backgroundColor: getLibraryColor(item.library),
                                  color: "white"
                                }}
                              >
                                {item.library.replace(/_/g, " ")}
                              </span>
                            </div>
                          </header>
                          <dl className="row-details">
                            <div className="row-item">
                              <dt className="row-key">P-value</dt>
                              <dd className="row-value">{item.p_value.toExponential(2)}</dd>
                            </div>
                            <div className="row-item">
                              <dt className="row-key">FDR</dt>
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
                    {/* Methods note */}
                    <div className="methods-note" style={{ 
                      marginTop: "16px", 
                      padding: "12px", 
                      backgroundColor: "#f5f5f5", 
                      borderRadius: "4px", 
                      fontSize: "12px", 
                      color: "#666",
                      borderLeft: "3px solid #2196f3"
                    }}>
                      <strong>Methods:</strong> Over-representation analysis via Enrichr (GSEApy). Libraries: KEGG 2021 Human, Reactome 2022, GO BP 2023. Multiple testing: adjusted p-value (FDR).
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              // Empty state when no enrichment results
              <div className="layout-column enrichment-column">
                <div className="card rows-card">
                  <header className="panel-header">
                    <h3 className="panel-title">Enrichment Results</h3>
                    <p className="panel-copy">
                      No significant enrichment results found for the analyzed genes.
                    </p>
                    {/* Gene count chips even for empty state */}
                    <div className="gene-count-chips" style={{ marginTop: "8px" }}>
                      <span 
                        className="gene-count-chip" 
                        title="Symbols normalized with mygene.info (Human)."
                        style={{ 
                          display: "inline-block", 
                          padding: "4px 8px", 
                          marginRight: "8px", 
                          backgroundColor: "#e3f2fd", 
                          color: "#1976d2", 
                          borderRadius: "12px", 
                          fontSize: "12px",
                          cursor: "help"
                        }}
                      >
                        Used genes: {(partialResult?.valid_genes?.length || result?.valid_genes?.length) || 0}
                      </span>
                      <span 
                        className="gene-count-chip" 
                        title="Symbols normalized with mygene.info (Human)."
                        style={{ 
                          display: "inline-block", 
                          padding: "4px 8px", 
                          backgroundColor: "#fff3e0", 
                          color: "#f57c00", 
                          borderRadius: "12px", 
                          fontSize: "12px",
                          cursor: "help"
                        }}
                      >
                        Unrecognized: {(partialResult?.invalid_genes?.length || result?.invalid_genes?.length) || 0}
                      </span>
                    </div>
                  </header>
                  <div className="card-content">
                    <div style={{ 
                      padding: "24px", 
                      textAlign: "center", 
                      color: "#666",
                      fontStyle: "italic"
                    }}>
                      No significant pathways or processes were enriched in this gene set.
                    </div>
                    {/* Methods note even for empty state */}
                    <div className="methods-note" style={{ 
                      marginTop: "16px", 
                      padding: "12px", 
                      backgroundColor: "#f5f5f5", 
                      borderRadius: "4px", 
                      fontSize: "12px", 
                      color: "#666",
                      borderLeft: "3px solid #2196f3"
                    }}>
                      <strong>Methods:</strong> Over-representation analysis via Enrichr (GSEApy). Libraries: KEGG 2021 Human, Reactome 2022, GO BP 2023. Multiple testing: adjusted p-value (FDR).
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Analyzed Genes Column */}
            <div className="layout-column genes-column">
              <div className="card">
                <header className="panel-header">
                  <h3 className="panel-title">Analyzed Genes</h3>
                </header>
                <div className="card-content">
                  <div className="value-pills">
                    {(partialResult?.valid_genes || result?.valid_genes || []).map((gene, index) => (
                      <span key={index} className="value-pill">
                        {gene}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Warnings - Full Width */}
          {((partialResult && partialResult.warnings.length > 0) || (result && result.warnings.length > 0)) && (
            <div className="layout-row">
              <div className="layout-column full-width">
                <div className="card">
                  <header className="panel-header">
                    <h3 className="panel-title">Warnings</h3>
                  </header>
                  <div className="card-content">
                    <div className="alert" role="alert">
                      {(partialResult?.warnings || result?.warnings || []).map((warning, index) => (
                        <div key={index}>{warning}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Dot Plot Drawer */}
          {selectedTerm && (
            <div className="layout-row">
              <div className="layout-column full-width">
                <div className="card">
                  <header className="panel-header">
                    <h3 className="panel-title">Overlap Genes: {selectedTerm.term}</h3>
                    <p className="panel-copy">
                      Library: {selectedTerm.library.replace(/_/g, " ")} • {selectedTerm.genes.length} genes
                    </p>
                    <button
                      onClick={() => setSelectedTerm(null)}
                      style={{
                        position: "absolute",
                        top: "16px",
                        right: "16px",
                        background: "none",
                        border: "none",
                        fontSize: "20px",
                        cursor: "pointer",
                        color: "#666"
                      }}
                    >
                      ×
                    </button>
                  </header>
                  <div className="card-content">
                    <div className="value-pills">
                      {selectedTerm.genes.map((gene, index) => (
                        <span key={index} className="value-pill">
                          {gene}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}
      </div>
    </div>
  );
}
