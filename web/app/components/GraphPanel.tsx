"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import MiniGraph from "./MiniGraph";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppContext, type QueryResponse } from "../contexts/AppContext";
import { csvEscape, downloadCsv } from "../utils/csv";
import type { ExampleQuery, ExampleQueryTab, ExampleQueriesByTab } from "../types/exampleQueries";
import { groupByTab, findExampleByQuestion } from "../types/exampleQueries";
import exampleQueriesData from "../data/exampleQueries.json";

type GraphPanelProps = {
  rows: Array<Record<string, unknown>>;
  initialQuestion?: string | null;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL;

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

// Schema-driven column order preference (based on prompts.py schema)
const PREFERRED_COLUMN_ORDER = [
  // Core identifiers
  'variant_name',
  'gene_symbol',
  'therapy_name',
  'therapies', // Array of therapy names (aggregated format)
  // AFFECTS fields
  'effect',
  'disease_name',
  'pmids',
  'evidence_levels',
  'evidence_count',
  'avg_rating',
  'max_rating',
  // TARGETS fields
  'targets_moa',
  'ref_sources',
  'ref_ids',
  'ref_urls',
];

const COLUMN_MIN_WIDTHS: Record<string, number> = {
  gene_symbol: 100,
  therapy_name: 140,
  therapies: 200, // Wider for array of therapy names
  effect: 120,
  disease_name: 160,
  pmids: 100,
  evidence_levels: 130,
  evidence_count: 100,
  avg_rating: 90,
  max_rating: 90,
};

// Shortened column labels for display
const COLUMN_LABELS: Record<string, string> = {
  variant_name: 'Variant',
  gene_symbol: 'Gene',
  therapy_name: 'Therapy',
  therapies: 'Therapies', // Array of therapy names
  effect: 'Effect',
  disease_name: 'Disease',
  pmids: 'PMIDs',
  evidence_levels: 'Evidence',
  evidence_count: '# Evid',
  avg_rating: 'Avg Rating',
  max_rating: 'Max Rating',
  targets_moa: 'MOA',
  ref_sources: 'Sources',
  ref_ids: 'Ref IDs',
  ref_urls: 'Ref URLs',
};

// Evidence level ranking for sorting (A is strongest)
const EVIDENCE_LEVEL_RANK: Record<string, number> = {
  'A': 0,
  'B': 1,
  'C': 2,
  'D': 3,
  'E': 4,
};

// Comparator for evidence levels (A < B < C < D < E)
const compareEvidenceLevels = (a: string, b: string): number => {
  const rankA = EVIDENCE_LEVEL_RANK[a.toUpperCase()] ?? 999;
  const rankB = EVIDENCE_LEVEL_RANK[b.toUpperCase()] ?? 999;
  return rankA - rankB;
};

// Get the best (strongest) evidence level from a row's evidence_levels array
const getBestEvidenceLevel = (row: Record<string, unknown>): string | null => {
  const evidenceLevels = row.evidence_levels;
  if (!Array.isArray(evidenceLevels) || evidenceLevels.length === 0) {
    return null;
  }
  
  const sanitized = sanitizeArrayValue(evidenceLevels);
  if (sanitized.length === 0) {
    return null;
  }
  
  const sorted = [...sanitized]
    .map(item => String(item).toUpperCase())
    .sort(compareEvidenceLevels);
  
  return sorted[0] ?? null;
};

// Sort rows by best evidence level (A is strongest, so A comes first)
const sortRowsByBestEvidence = (rows: Array<Record<string, unknown>>): Array<Record<string, unknown>> => {
  return [...rows].sort((a, b) => {
    const bestA = getBestEvidenceLevel(a);
    const bestB = getBestEvidenceLevel(b);
    
    // Rows with no evidence levels go to the end
    if (!bestA && !bestB) return 0;
    if (!bestA) return 1;
    if (!bestB) return -1;
    
    // Compare by evidence level rank (lower rank = stronger evidence)
    const rankA = EVIDENCE_LEVEL_RANK[bestA] ?? 999;
    const rankB = EVIDENCE_LEVEL_RANK[bestB] ?? 999;
    return rankA - rankB;
  });
};

// Infer dynamic columns from rows with schema-driven ordering
const inferColumns = (rows: Array<Record<string, unknown>>): string[] => {
  if (!rows || rows.length === 0) return [];
  
  // Collect all unique keys from all rows
  const allKeys = new Set<string>();
  rows.forEach(row => {
    Object.keys(row).forEach(key => {
      // Exclude best_evidence_level as it's redundant with sorted evidence_levels
      if (key !== 'best_evidence_level' && isMeaningfulValue(row[key])) {
        allKeys.add(key);
      }
    });
  });
  
  // Order columns: preferred order first, then remaining alphabetically
  const preferred = PREFERRED_COLUMN_ORDER.filter(key => allKeys.has(key));
  const remaining = Array.from(allKeys)
    .filter(key => !PREFERRED_COLUMN_ORDER.includes(key))
    .sort();
  
  return [...preferred, ...remaining];
};

// Render cell value based on type (reusing existing formatting logic)
const renderCellValue = (value: unknown, columnKey?: string): React.ReactNode => {
  if (value === null || value === undefined) {
    return <span className="cell-empty">—</span>;
  }

  if (Array.isArray(value)) {
    const sanitized = sanitizeArrayValue(value);
    if (!sanitized.length) {
      return <span className="cell-empty">—</span>;
    }

    if (columnKey === "pmids") {
      return (
        <div className="value-stack">
          {sanitized.map((item, pillIndex) => (
            <span key={pillIndex} className="value-stack-item">
              {String(item)}
            </span>
          ))}
        </div>
      );
    }

    if (columnKey === "evidence_levels") {
      // Sort evidence levels: A (strongest) to E (weakest)
      const sorted = [...sanitized]
        .map(item => String(item).toUpperCase())
        .sort(compareEvidenceLevels);
      
      return (
        <div className="value-pills">
          {sorted.map((level, index) => (
            <span
              key={level}
              className={`value-pill ${index === 0 ? "value-pill-strong" : ""}`}
              title={index === 0 ? "Strongest evidence level" : undefined}
            >
              {level}
            </span>
          ))}
        </div>
      );
    }

    return (
      <div className="value-pills">
        {sanitized.map((item, pillIndex) => {
          if (typeof item === "string") {
            return isHttpUrl(item) ? (
              <a
                key={pillIndex}
                className="value-pill value-pill-link"
                href={item}
                target="_blank"
                rel="noreferrer"
              >
                {getUrlLabel(item)}
              </a>
            ) : (
              <span key={pillIndex} className="value-pill">
                {item}
              </span>
            );
          }
          return (
            <span key={pillIndex} className="value-pill">
              {String(item)}
            </span>
          );
        })}
      </div>
    );
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return <span className="cell-empty">—</span>;
    }

    return isHttpUrl(trimmed) ? (
      <a className="value-link" href={trimmed} target="_blank" rel="noreferrer">
        {getUrlLabel(trimmed)}
      </a>
    ) : (
      <span>{trimmed}</span>
    );
  }

  if (typeof value === "object" && value !== null) {
    return (
      <pre className="value-json">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  // Format rating columns to 1 decimal place
  if ((columnKey === "avg_rating" || columnKey === "max_rating") && typeof value === "number") {
    return <span>{value.toFixed(1)}</span>;
  }

  return <span>{String(value)}</span>;
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
  const [copyJsonSuccess, setCopyJsonSuccess] = useState(false);
  const [noCache, setNoCache] = useState(false);
  const [showCacheToggle, setShowCacheToggle] = useState(false);
  const [isMounted, setIsMounted] = useState(false);
  const [activeExampleTab, setActiveExampleTab] = useState<ExampleQueryTab>("therapy_targets");
  const hasPersistedPreference = useRef(false);

  // Load and group example queries
  const exampleQueries = useMemo(() => exampleQueriesData as ExampleQuery[], []);
  const groupedExamples = useMemo(() => groupByTab(exampleQueries), [exampleQueries]);
  const geneSymbols = useMemo(
    () => (result?.rows ? extractGeneSymbols(result.rows) : []),
    [result?.rows]
  );
  const hasRows = Boolean(result?.rows?.length);
  const columns = useMemo(
    () => (result?.rows ? inferColumns(result.rows) : []),
    [result?.rows]
  );

  // Initialize from localStorage and set mounted flag after hydration
  useEffect(() => {
    setIsMounted(true);
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("oncograph_no_cache");
      if (saved === "true") {
        setNoCache(true);
        // Show toggle if user has previously enabled it
        setShowCacheToggle(true);
      } else if (saved === "false") {
        // User has interacted before but currently has it disabled
        setShowCacheToggle(true);
      }
      // If saved is null, user has never interacted, so keep toggle hidden
    }
  }, []);

  // Save to localStorage when the user changes the toggle (skip the first hydration run)
  useEffect(() => {
    if (!isMounted || typeof window === "undefined") {
      return;
    }

    if (!hasPersistedPreference.current) {
      hasPersistedPreference.current = true;
      return;
    }

    localStorage.setItem("oncograph_no_cache", String(noCache));
    if (!showCacheToggle) {
      setShowCacheToggle(true);
    }
  }, [noCache, isMounted, showCacheToggle]);

  // Global keyboard shortcut to toggle cache override (Ctrl+Shift+C)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === "C") {
        e.preventDefault();
        setNoCache((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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

    setFeedbackSubmitted(false);
    
    // Check if backend is awake before starting the actual query
    let backendWaking = false;
    try {
      const healthCheckPromise = fetch(`${API_URL}/healthz`, { signal: AbortSignal.timeout(3000) });
      await healthCheckPromise;
      // Backend is awake - proceed normally
    } catch (err) {
      // Backend is sleeping - show wake-up message
      backendWaking = true;
    }

    setGraphState({ 
      question: trimmed,
      lastQuery: trimmed,
      isLoading: true,
      error: null,
      result: null,
      progress: backendWaking ? "Render Backend is waking up (may take 1-2 minutes)..." : null,
      run_id: null
    });

    // Try SSE first for progress streaming
    const url = `${API_URL}/query/stream?question=${encodeURIComponent(trimmed)}${noCache ? "&no_cache=true" : ""}`;
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
              const response = await fetch(`${API_URL}/query?no_cache=${noCache}`, {
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
        const response = await fetch(`${API_URL}/query?no_cache=${noCache}`, {
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
  }, [noCache, setGraphState, setDotCount]);

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

  // Handle clicking an example query
  function handleExampleClick(example: ExampleQuery) {
    if (isLoading) return;

    // If cached response exists, hydrate state immediately
    if (example.cachedResponse) {
      setGraphState({
        question: example.question,
        lastQuery: example.question,
        result: {
          answer: example.cachedResponse.answer,
          cypher: example.cachedResponse.cypher,
          rows: example.cachedResponse.rows,
          run_id: `cached-${example.id}`,
        },
        error: null,
        isLoading: false,
        progress: null,
        run_id: `cached-${example.id}`,
      });
    } else {
      // Just prefill the question
      setGraphState({ question: example.question });
    }
  }

  // Handle copying example JSON for cache
  async function handleCopyExampleJson() {
    if (!result || !lastQuery) return;

    const matchingExample = findExampleByQuestion(exampleQueries, lastQuery);
    if (!matchingExample) return;

    const cacheEntry = {
      id: matchingExample.id,
      tab: matchingExample.tab,
      question: matchingExample.question,
      cachedResponse: {
        answer: result.answer,
        cypher: result.cypher,
        rows: result.rows,
        updatedAt: new Date().toISOString(),
      },
    };

    const jsonString = JSON.stringify(cacheEntry, null, 2);
    
    try {
      await navigator.clipboard.writeText(jsonString);
      setCopyJsonSuccess(true);
      setTimeout(() => setCopyJsonSuccess(false), 3000);
    } catch (err) {
      console.error("Failed to copy to clipboard:", err);
    }
  }

  // Check if current query matches an example
  const currentExample = useMemo(() => {
    if (!lastQuery) return null;
    return findExampleByQuestion(exampleQueries, lastQuery);
  }, [lastQuery, exampleQueries]);

  // Handle moving genes to Hypothesis Analyzer
  function handleMoveToHypothesisAnalyzer() {
    if (geneSymbols.length === 0) return;
    
    const geneString = geneSymbols.join(", ");
    
    // Get current genes from hypothesis state and append
    const currentGenes = hypothesisState.genes.trim();
    const newGenes = currentGenes ? `${currentGenes}, ${geneString}` : geneString;
    setHypothesisState({ genes: newGenes });
    
    // Navigate to hypotheses tab
    router.push('/hypotheses');
  }

  const buildGraphCsv = useCallback(
    (exportRows: Array<Record<string, unknown>>) => {
      const columns = Array.from(
        exportRows.reduce((set, row) => {
          Object.keys(row).forEach((key) => set.add(key));
          return set;
        }, new Set<string>())
      ).sort();

      const metadataLines = [
        ["# Export Type", "Graph QA"],
        ["# Question", lastQuery ?? ""],
        ["# Run ID", run_id ?? ""],
        ["# Generated At", new Date().toISOString()],
        ["# API Endpoint", API_URL ?? ""],
        ["# Row Count", exportRows.length.toString()],
        [],
        columns,
      ];

      const dataLines = exportRows.map((row) =>
        columns.map((col) => {
          const value = row[col];
          if (Array.isArray(value)) {
            return value.join("; ");
          }
          if (typeof value === "object" && value !== null) {
            return JSON.stringify(value);
          }
          return value ?? "";
        })
      );

      return [...metadataLines, ...dataLines]
        .map((line) => line.map(csvEscape).join(","))
        .join("\n");
    },
    [lastQuery, run_id]
  );

  const handleExportRows = useCallback(() => {
    if (!hasRows || !result?.rows) return;
    const csvContent = buildGraphCsv(result.rows);
    const filename = `graph-qa_${run_id ?? Date.now()}.csv`;
    downloadCsv(filename, csvContent);
  }, [buildGraphCsv, hasRows, result?.rows, run_id]);

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
                
                {/* Hidden cache override toggle - accessible via dev tools or keyboard shortcut (Ctrl+Shift+C) */}
                <div style={{ 
                  position: "absolute", 
                  top: "-9999px", 
                  left: "-9999px",
                  opacity: 0,
                  pointerEvents: "none"
                }}>
                  <label>
                    <input
                      type="checkbox"
                      checked={noCache}
                      onChange={(e) => setNoCache(e.target.checked)}
                      onKeyDown={(e) => {
                        // Toggle with Ctrl+Shift+C
                        if (e.ctrlKey && e.shiftKey && e.key === "C") {
                          e.preventDefault();
                          setNoCache((prev) => !prev);
                        }
                      }}
                      tabIndex={-1}
                    />
                    Disable Cache (for testing prompts)
                  </label>
                </div>
                
                {/* Visible toggle - show if localStorage has been set (user has interacted with it before) */}
                {isMounted && showCacheToggle && (
                  <div style={{ 
                    marginTop: "8px", 
                    fontSize: "12px", 
                    color: "#666",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px"
                  }}>
                    <input
                      type="checkbox"
                      id="no-cache-toggle"
                      checked={noCache}
                      onChange={(e) => setNoCache(e.target.checked)}
                      style={{ cursor: "pointer" }}
                    />
                    <label htmlFor="no-cache-toggle" style={{ cursor: "pointer", userSelect: "none" }}>
                      Disable cache (for testing prompts)
                    </label>
                  </div>
                )}
                
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
                <div className="tab-navigation" style={{ marginBottom: "12px" }}>
                  <button
                    type="button"
                    className={`tab-button ${activeExampleTab === "therapy_targets" ? "active" : ""}`}
                    onClick={() => setActiveExampleTab("therapy_targets")}
                  >
                    Therapy & Targets
                  </button>
                  <button
                    type="button"
                    className={`tab-button ${activeExampleTab === "biomarkers_resistance" ? "active" : ""}`}
                    onClick={() => setActiveExampleTab("biomarkers_resistance")}
                  >
                    Biomarkers & Resistance
                  </button>
                  <button
                    type="button"
                    className={`tab-button ${activeExampleTab === "evidence_precision" ? "active" : ""}`}
                    onClick={() => setActiveExampleTab("evidence_precision")}
                  >
                    Evidence & Precision
                  </button>
                </div>
                <div className="examples" aria-label="Example queries">
                  <div className="examples-grid">
                    {groupedExamples[activeExampleTab].map((example) => (
                      <button
                        key={example.id}
                        type="button"
                        className="example-button"
                        onClick={() => handleExampleClick(example)}
                        disabled={isLoading}
                        title={example.cachedResponse ? "Click to load cached result" : "Click to run query"}
                      >
                        {example.question}
                        {example.cachedResponse && (
                          <span style={{ marginLeft: "8px", fontSize: "11px", opacity: 0.7 }}>✓</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
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

            {/* Row 3: Results Table | Cypher Query */}
            <div className="layout-row">
              <div className="layout-column rows-column">
                <div className="card">
                  <header className="panel-header">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                      <div style={{ flex: 1 }}>
                        <h3 className="panel-title">Results Table</h3>
                        <p className="panel-copy">
                          Explore the raw query results with references.
                        </p>
                      </div>
                      {(geneSymbols.length > 0 || hasRows) && (
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          {geneSymbols.length > 0 && (
                            <>
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
                                title={`Copy ${geneSymbols.length} gene symbols to clipboard`}
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
                                title={`Move ${geneSymbols.length} gene symbols to Hypothesis Analyzer`}
                              >
                                <span>🧬</span>
                                <span>Move to Hypothesis Analyzer</span>
                              </button>
                            </>
                          )}
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={handleExportRows}
                            style={{
                              fontSize: '12px',
                              padding: '6px 12px'
                            }}
                            disabled={!hasRows}
                            title="Download results table with metadata as CSV"
                          >
                            ⬇ Download CSV
                          </button>
                        </div>
                      )}
                    </div>
                  </header>
                  <div className="card-content">
                    {result.rows?.length && columns.length > 0 ? (
                      <div className="results-table-container">
                        <table className="results-table">
                          <thead>
                            <tr>
                              {columns.map((col) => (
                                <th
                                  key={col}
                                  className="results-table-header"
                                  style={{
                                    minWidth: COLUMN_MIN_WIDTHS[col] ?? 100,
                                  }}
                                >
                                  {COLUMN_LABELS[col] ?? formatKeyLabel(col)}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {sortRowsByBestEvidence(result.rows).map((row, index) => (
                              <tr key={index} className="results-table-row">
                                {columns.map((col) => (
                                  <td
                                    key={col}
                                    className="results-table-cell"
                                    style={{
                                      minWidth: COLUMN_MIN_WIDTHS[col] ?? 100,
                                    }}
                                  >
                                    {renderCellValue(row[col], col)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
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

                    {/* Copy Example JSON Section (dev-only, shown when current query matches an example) */}
                    {currentExample && (
                      <div className="feedback-section" style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                        <p style={{ margin: '0 0 12px 0', fontSize: '14px', color: '#6b7280' }}>
                          Update example cache:
                        </p>
                        {copyJsonSuccess ? (
                          <p style={{ margin: '0', fontSize: '14px', color: '#10b981' }}>
                            ✓ Example JSON copied to clipboard! Paste into exampleQueries.json
                          </p>
                        ) : (
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={handleCopyExampleJson}
                            style={{ fontSize: '14px', padding: '6px 12px' }}
                            title="Copy JSON snippet to update exampleQueries.json with this result"
                          >
                            Copy Example JSON for Cache
                          </button>
                        )}
                      </div>
                    )}
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
