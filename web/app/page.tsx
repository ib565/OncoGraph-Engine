"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import MiniGraph from "./components/MiniGraph";
import HypothesisAnalyzer from "./components/HypothesisAnalyzer";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type QueryResponse = {
  answer: string;
  cypher: string;
  rows: Array<Record<string, unknown>>;
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

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const sseRef = useRef<EventSource | null>(null);
  const [dotCount, setDotCount] = useState(0);
  const [lastQuery, setLastQuery] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"query" | "analyzer">("query");

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

  async function runQuery(input: string) {
    const trimmed = input.trim();

    if (!trimmed) {
      setQuestion("");
      return;
    }

    setQuestion(trimmed);
    setLastQuery(trimmed);

    if (!API_URL) {
      setError("NEXT_PUBLIC_API_URL is not configured");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    setProgress(null);

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
            setProgress(data.message);
            setDotCount(0);
          }
        } catch {
          // ignore malformed
        }
      });

      es.addEventListener("result", (evt: MessageEvent) => {
        try {
          const data = JSON.parse(evt.data) as QueryResponse;
          setResult(data);
        } catch {
          setError("Malformed result from server");
        } finally {
          setProgress(null);
          close();
          setIsLoading(false);
        }
      });

      es.addEventListener("error", (evt: MessageEvent) => {
        try {
          const data = JSON.parse((evt as MessageEvent).data) as { message?: string };
          setError(data?.message || "Request failed");
        } catch {
          setError("Request failed");
        } finally {
          setProgress(null);
          close();
          setIsLoading(false);
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
              setResult(data);
            } catch (err) {
              const message = err instanceof Error ? err.message : String(err);
              setError(message);
            } finally {
              setProgress(null);
              setIsLoading(false);
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
        setResult(data);
      } catch (fallbackErr) {
        const message = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
        setError(message);
      } finally {
        setProgress(null);
        setIsLoading(false);
      }
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runQuery(question);
  }

  return (
    <main className="page">
      <header className="hero">
        <h1 className="hero-title">OncoGraph Agent</h1>
        <p className="hero-copy">
          Answers cancer genomics questions using knowledge-graph-backed citations.
        </p>
      </header>

      {/* Tab Navigation */}
      <div className="tab-navigation">
        <button
          className={`tab-button ${activeTab === "query" ? "active" : ""}`}
          onClick={() => setActiveTab("query")}
        >
          Knowledge Graph Query
        </button>
        <button
          className={`tab-button ${activeTab === "analyzer" ? "active" : ""}`}
          onClick={() => setActiveTab("analyzer")}
        >
          Hypothesis Analyzer
        </button>
      </div>

      {activeTab === "query" && (
        <section className="card query-card">
        <div className="card-heading">
          <h2 className="card-title">Interrogate the knowledge graph</h2>
          <p className="card-subtitle">
            Craft a precise oncology question or load an example to uncover graph-backed
            evidence, interactive context, and traceable references.
          </p>
        </div>
        <form className="query-form" onSubmit={handleSubmit}>
          <input
            className="query-input"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
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

        {EXAMPLE_QUERIES.length > 0 && (
          <div className="examples" aria-label="Example queries">
            <span className="examples-label">Example queries</span>
            <div className="examples-grid">
              {EXAMPLE_QUERIES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="example-button"
                  onClick={() => {
                    void runQuery(example);
                  }}
                  disabled={isLoading}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
        </section>
      )}

      {activeTab === "analyzer" && (
        <HypothesisAnalyzer 
          onNavigateToQuery={(question: string) => {
            setQuestion(question);
            setActiveTab("query");
          }}
        />
      )}

      {activeTab === "query" && error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      {activeTab === "query" && isLoading && progress && !error && (
        <div className="status-message" role="status" aria-live="polite">
          {animatedProgress ?? progress}
        </div>
      )}

      {activeTab === "query" && result && (
        <section className="result-overview">
          <div className="primary-column">
            <section className="card answer-card">
              {lastQuery && (
                <p className="question-text">
                  <span className="question-label">Question</span>
                  {lastQuery}
                </p>
              )}
              <h2 className="section-title">Answer</h2>
              <div className="answer-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown>
              </div>
            </section>

            <section className="card graph-card">
              <header className="panel-header">
                <h3 className="panel-title">Interactive subgraph</h3>
                <p className="panel-copy">
                  Inspect entities and relationships driving the synthesized answer. Drag to reposition nodes for clarity.
                </p>
              </header>
              <div className="graph-shell">
                <MiniGraph rows={result.rows} height={440} />
              </div>
            </section>

            <section className="card rows-card">
              <header className="panel-header">
                <h3 className="panel-title">Cypher rows</h3>
                <p className="panel-copy">
                  Explore the raw query results with references.
                </p>
              </header>
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
            </section>
          </div>

          <aside className="secondary-column">
            <section className="card cypher-card">
              <header className="panel-header">
                <h3 className="panel-title">Cypher query</h3>
                <p className="panel-copy">Reference the exact graph query executed.</p>
              </header>
              <div className="cypher-scroll">
                <pre className="code-block">{result.cypher}</pre>
            </div>
            </section>
          </aside>
        </section>
      )}
    </main>
  );
}

