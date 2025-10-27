"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import MiniGraph from "./MiniGraph";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppContext, type QueryResponse } from "../contexts/AppContext";

type GraphPanelProps = {
  rows: Array<Record<string, unknown>>;
  initialQuestion?: string | null;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const EXAMPLE_QUERIES: string[] = [
  "What biomarkers predict resistance to anti-EGFR therapies in colorectal cancer?",
  "Which therapies target KRAS and what are their mechanisms of action?",
  "What is the predicted response of EGFR L858R to Gefitinib in Lung Cancer?",
];

const HTTP_URL_REGEX = /^https?:\/\//i;

const formatKeyLabel = (label: string) =>
  label
    .replace(/[_\-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());

const sanitizeArrayValue = (value: unknown[]) =>
  value
    .map((item) => (typeof item === "string" ? item.trim() : item))
    .filter((item) => {
      if (item === null || item === undefined) return false;
      if (typeof item === "string") return item.length > 0;
      return true;
    });

const isMeaningfulValue = (value: unknown): boolean => {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) {
    return sanitizeArrayValue(value).length > 0;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return true;
};

const isHttpUrl = (value: string) => HTTP_URL_REGEX.test(value);

const getUrlLabel = (value: string) => {
  try {
    const url = new URL(value);
    return url.hostname.replace(/^www\./, "");
  } catch {
    return value;
  }
};

// Helper function to extract and deduplicate gene symbols from result rows
const extractGeneSymbols = (rows: Array<Record<string, unknown>>): string[] => {
  const geneSymbols = new Set<string>();
  
  rows.forEach(row => {
    if (row.gene_symbol && typeof row.gene_symbol === 'string' && row.gene_symbol.trim()) {
      geneSymbols.add(row.gene_symbol.trim());
    }
  });
  
  return Array.from(geneSymbols).sort();
};

export default function GraphPanel({ rows, initialQuestion }: GraphPanelProps) {
  const { graphState, setGraphState, setHypothesisState, hypothesisState } = useAppContext();
  const { question, result, error, isLoading, progress, lastQuery, run_id } = graphState;
  const router = useRouter();
  
  const sseRef = useRef<EventSource | null>(null);
  const [dotCount, setDotCount] = useState(0);
  const initialTriggerRef = useRef<string | null>(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  useEffect(() => {
    if (!isLoading || !progress) {
      setDotCount(0);
      return;
    }

    const id = window.setInterval(() => {
      setDotCount((count) => (count + 1) % 4);
    }, 400);

    return () => {
      window.clearInterval(id);
      setDotCount(0);
    };
  }, [isLoading, progress]);

  const animatedProgress = progress
    ? `${progress}${dotCount === 0 ? "" : ".".repeat(dotCount)}`
    : null;

  const runQuery = useCallback(async (input: string) => {
    const trimmed = input.trim();

    if (!trimmed) {
      setGraphState({ question: "" });
      return;
    }

    setGraphState({ 
      question: trimmed,
      lastQuery: trimmed,
      isLoading: true,
      error: null,
      result: null,
      progress: null,
      run_id: null
    });
    setFeedbackSubmitted(false);

    // Try SSE first for progress streaming
    const url = `${API_URL}/query/stream?question=${encodeURIComponent(trimmed)}`;
    try {
      const es = new EventSource(url, { withCredentials: false });
      sseRef.current = es;

      const close = () => {
        if (sseRef.current) {
          sseRef.current.close();
          sseRef.current = null;
        }
      };

      es.addEventListener("progress", (evt: MessageEvent) => {
        try {
          const data = JSON.parse(evt.data) as { message?: string };
          if (data?.message) {
            setGraphState({ progress: data.message });
            setDotCount(0);
          }
        } catch {
          // ignore malformed
        }
      });

      es.addEventListener("result", (evt: MessageEvent) => {
        try {
          const data = JSON.parse(evt.data) as QueryResponse;
          setGraphState({ result: data, run_id: data.run_id });
        } catch {
          setGraphState({ error: "Malformed result from server" });
        } finally {
          setGraphState({ progress: null, isLoading: false });
          close();
        }
      });

      es.addEventListener("error", (evt: MessageEvent) => {
        try {
          const data = JSON.parse((evt as MessageEvent).data) as { message?: string };
          setGraphState({ error: data?.message || "Request failed" });
        } catch {
          setGraphState({ error: "Request failed" });
        } finally {
          setGraphState({ progress: null, isLoading: false });
          close();
        }
      });

      // If the connection errors immediately (e.g., CORS/proxy), fall back to POST
      es.onerror = () => {
        // Avoid infinite loop if already closed due to a server-sent error event
        if (sseRef.current) {
          close();
          void (async () => {
            try {
              const response = await fetch(`${API_URL}/query`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: trimmed }),
              });
              if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                const detail = (payload as any)?.detail;
                if (detail?.message) throw new Error(detail.message);
                throw new Error(`Request failed with status ${response.status}`);
              }
              const data = (await response.json()) as QueryResponse;
              setGraphState({ result: data, run_id: data.run_id });
            } catch (err) {
              const message = err instanceof Error ? err.message : String(err);
              setGraphState({ error: message });
            } finally {
              setGraphState({ progress: null, isLoading: false });
            }
          })();
        }
      };
    } catch (err) {
      // As a safety net, fall back to POST if constructing EventSource throws
      try {
        const response = await fetch(`${API_URL}/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: trimmed }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          const detail = (payload as any)?.detail;
          if (detail?.message) throw new Error(detail.message);
          throw new Error(`Request failed with status ${response.status}`);
        }
        const data = (await response.json()) as QueryResponse;
        setGraphState({ result: data, run_id: data.run_id });
      } catch (fallbackErr) {
        const message = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
        setGraphState({ error: message });
      } finally {
        setGraphState({ progress: null, isLoading: false });
      }
    }
  }, []);

  useEffect(() => {
    const trimmedInitial = initialQuestion?.trim();
    if (!trimmedInitial) return;
    if (initialTriggerRef.current === trimmedInitial) return;

    initialTriggerRef.current = trimmedInitial;
    // Only populate the question text area, don't run the query automatically
    // This allows users to edit the question before running it
    setGraphState({ question: trimmedInitial });
  }, [initialQuestion, setGraphState]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runQuery(question);
  }

  async function submitFeedback(cypherCorrect: boolean) {
    if (!run_id) return;
    
    setFeedbackLoading(true);
    try {
      const response = await fetch(`${API_URL}/query/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          run_id, 
          cypher_correct: cypherCorrect 
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Feedback submission failed with status ${response.status}`);
      }
      
      setFeedbackSubmitted(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("Failed to submit feedback:", message);
      // Don't show error to user for feedback - it's optional
    } finally {
      setFeedbackLoading(false);
    }
  }

  // Handle copying genes to clipboard
  async function handleCopyGenes() {
    if (!result?.rows) return;
    
    const geneSymbols = extractGeneSymbols(result.rows);
    if (geneSymbols.length === 0) return;
    
    const geneString = geneSymbols.join(", ");
    
    try {
      await navigator.clipboard.writeText(geneString);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy to clipboard:", err);
    }
  }

  // Handle moving genes to Hypothesis Analyzer
  function handleMoveToHypothesisAnalyzer() {
    if (!result?.rows) return;
    
    const geneSymbols = extractGeneSymbols(result.rows);
    if (geneSymbols.length === 0) return;
    
    const geneString = geneSymbols.join(", ");
    
    // Get current genes from hypothesis state and append
    const currentGenes = hypothesisState.genes.trim();
    const newGenes = currentGenes ? `${currentGenes}, ${geneString}` : geneString;
    setHypothesisState({ genes: newGenes });
    
    // Navigate to hypotheses tab
    router.push('/hypotheses');
  }

  return (
    <div className="graph-panel">
      <div className="panel-header">
        <h3 className="panel-title">Knowledge Graph Query</h3>
      </div>
      <div className="panel-content">
        {/* Row 1: Query Input | Example Queries */}
        <div className="layout-row">
          <div className="layout-column query-column">
            <div className="card">
              <header className="panel-header">
                <h3 className="panel-title">Query</h3>
              </header>
              <div className="card-content">
                <form className="query-form" onSubmit={handleSubmit}>
                  <input
                    className="query-input"
                    value={question}
                    onChange={(event) => setGraphState({ question: event.target.value })}
                    placeholder="e.g. Do KRAS mutations affect response to anti-EGFR therapy in colorectal cancer?"
                    disabled={isLoading}
                  />
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={isLoading || !question.trim()}
                  >
                    {isLoading ? "Running..." : "Ask"}
                  </button>
                </form>
                
                {error && (
                  <div className="alert" role="alert">
                    {error}
                  </div>
                )}

                {isLoading && progress && !error && (
                  <div className="status-message" role="status" aria-live="polite">
                    {animatedProgress ?? progress}
                  </div>
                )}
              </div>
            </div>
          </div>
          
          <div className="layout-column examples-column">
            <div className="card">
              <header className="panel-header">
                <h3 className="panel-title">Example Queries</h3>
              </header>
              <div className="card-content">
                {EXAMPLE_QUERIES.length > 0 && (
                  <div className="examples" aria-label="Example queries">
                    <div className="examples-grid">
                      {EXAMPLE_QUERIES.map((example) => (
                        <button
                          key={example}
                          type="button"
                          className="example-button"
                          onClick={() => {
                            setGraphState({ question: example });
                          }}
                          disabled={isLoading}
                        >
                          {example}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {result && (
          <>
            {/* Row 2: Answer | Subgraph */}
            <div className="layout-row">
              <div className="layout-column answer-column">
                <div className="card">
                  <header className="panel-header">
                    <h3 className="panel-title">Answer</h3>
                  </header>
                  <div className="card-content">
                    {lastQuery && (
                      <p className="question-text">
                        <span className="question-label">Question</span>
                        {lastQuery}
                      </p>
                    )}
                    <div className="answer-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="layout-column subgraph-column">
                <div className="card">
                  <header className="panel-header">
                    <h3 className="panel-title">Interactive Subgraph</h3>
                    <p className="panel-copy">
                      Inspect entities and relationships driving the synthesized answer. Drag to reposition nodes for clarity.
                    </p>
                  </header>
                  <div className="card-content">
                    <div className="graph-shell">
                      <div className="graph-container">
                        <MiniGraph rows={result.rows} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Row 3: Cypher Rows | Cypher Query */}
            <div className="layout-row">
              <div className="layout-column rows-column">
                <div className="card">
                  <header className="panel-header">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                      <div style={{ flex: 1 }}>
                        <h3 className="panel-title">Cypher Rows</h3>
                        <p className="panel-copy">
                          Explore the raw query results with references.
                        </p>
                      </div>
                      {result?.rows && extractGeneSymbols(result.rows).length > 0 && (
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={handleCopyGenes}
                            style={{ 
                              fontSize: '12px', 
                              padding: '6px 12px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px'
                            }}
                            title={`Copy ${extractGeneSymbols(result.rows).length} gene symbols to clipboard`}
                          >
                            {copySuccess ? (
                              <>
                                <span>✓</span>
                                <span>Copied!</span>
                              </>
                            ) : (
                              <>
                                <span>📋</span>
                                <span>Copy Genes</span>
                              </>
                            )}
                          </button>
                          <button
                            type="button"
                            className="primary-button"
                            onClick={handleMoveToHypothesisAnalyzer}
                            style={{ 
                              fontSize: '12px', 
                              padding: '6px 12px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px'
                            }}
                            title={`Move ${extractGeneSymbols(result.rows).length} gene symbols to Hypothesis Analyzer`}
                          >
                            <span>🧬</span>
                            <span>Move to Hypothesis Analyzer</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </header>
                  <div className="card-content">
                    {result.rows?.length ? (
                      <div className="rows-scroll" role="list">
                        {result.rows.map((row, index) => {
                          const entries = Object.entries(row).filter(([, value]) => isMeaningfulValue(value));

                          if (entries.length === 0) {
                            return (
                              <article className="row-card" key={`row-${index}`} role="listitem">
                                <header className="row-heading">Row {index + 1}</header>
                                <p className="empty-row">No populated columns.</p>
                              </article>
                            );
                          }

                          return (
                            <article className="row-card" key={`row-${index}`} role="listitem">
                              <header className="row-heading">Row {index + 1}</header>
                              <dl className="row-details">
                                {entries.map(([key, value]) => {
                                  const label = formatKeyLabel(key);

                                  if (Array.isArray(value)) {
                                    const sanitized = sanitizeArrayValue(value);
                                    if (!sanitized.length) {
                                      return null;
                                    }

                                    return (
                                      <Fragment key={key}>
                                        <dt className="row-key">{label}</dt>
                                        <dd className="row-value">
                                          <div className="value-pills">
                                            {sanitized.map((item, pillIndex) => {
                                              if (typeof item === "string") {
                                                return isHttpUrl(item) ? (
                                                  <a
                                                    key={`${key}-${pillIndex}`}
                                                    className="value-pill value-pill-link"
                                                    href={item}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                  >
                                                    {getUrlLabel(item)}
                                                  </a>
                                                ) : (
                                                  <span
                                                    key={`${key}-${pillIndex}`}
                                                    className="value-pill"
                                                  >
                                                    {item}
                                                  </span>
                                                );
                                              }

                                              return (
                                                <span
                                                  key={`${key}-${pillIndex}`}
                                                  className="value-pill"
                                                >
                                                  {String(item)}
                                                </span>
                                              );
                                            })}
                                          </div>
                                        </dd>
                                      </Fragment>
                                    );
                                  }

                                  if (typeof value === "string") {
                                    const trimmed = value.trim();
                                    if (!trimmed) {
                                      return null;
                                    }

                                    return (
                                      <Fragment key={key}>
                                        <dt className="row-key">{label}</dt>
                                        <dd className="row-value">
                                          {isHttpUrl(trimmed) ? (
                                            <a
                                              className="value-link"
                                              href={trimmed}
                                              target="_blank"
                                              rel="noreferrer"
                                            >
                                              {getUrlLabel(trimmed)}
                                            </a>
                                          ) : (
                                            <span>{trimmed}</span>
                                          )}
                                        </dd>
                                      </Fragment>
                                    );
                                  }

                                  if (typeof value === "object" && value !== null) {
                                    return (
                                      <Fragment key={key}>
                                        <dt className="row-key">{label}</dt>
                                        <dd className="row-value">
                                          <pre className="value-json">
                                            {JSON.stringify(value, null, 2)}
                                          </pre>
                                        </dd>
                                      </Fragment>
                                    );
                                  }

                                  return (
                                    <Fragment key={key}>
                                      <dt className="row-key">{label}</dt>
                                      <dd className="row-value">{String(value)}</dd>
                                    </Fragment>
                                  );
                                })}
                              </dl>
                            </article>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="empty-state">No rows returned from the query.</p>
                    )}
                  </div>
                </div>
              </div>
              
              <div className="layout-column cypher-column">
                <div className="card">
                  <header className="panel-header">
                    <h3 className="panel-title">Cypher Query</h3>
                    <p className="panel-copy">Reference the exact graph query executed.</p>
                  </header>
                  <div className="card-content">
                    <div className="cypher-scroll">
                      <pre className="code-block">{result.cypher}</pre>
                    </div>
                    
                    {/* Feedback Section */}
                    <div className="feedback-section" style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                      <p style={{ margin: '0 0 12px 0', fontSize: '14px', color: '#6b7280' }}>
                        Was the Cypher generated correctly?
                      </p>
                      {feedbackSubmitted ? (
                        <p style={{ margin: '0', fontSize: '14px', color: '#10b981' }}>
                          ✓ Feedback recorded. Thank you!
                        </p>
                      ) : (
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => submitFeedback(true)}
                            disabled={feedbackLoading}
                            style={{ fontSize: '14px', padding: '6px 12px' }}
                          >
                            {feedbackLoading ? 'Submitting...' : 'Yes'}
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => submitFeedback(false)}
                            disabled={feedbackLoading}
                            style={{ fontSize: '14px', padding: '6px 12px' }}
                          >
                            {feedbackLoading ? 'Submitting...' : 'No'}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}

        {!result && (
          <div className="layout-row">
            <div className="layout-column full-width">
              <div className="card">
                <header className="panel-header">
                  <h3 className="panel-title">Knowledge Graph</h3>
                </header>
                <div className="card-content">
                  <div className="graph-container">
                    <MiniGraph rows={rows} height={400} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
