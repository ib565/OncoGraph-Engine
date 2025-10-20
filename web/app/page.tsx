"use client";

import { useEffect, useRef, useState } from "react";
import MiniGraph from "./components/MiniGraph";
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
  "Do KRAS G12C mutations affect response to Sotorasib in Lung Cancer?",
  "Find me the PubMed citations related to Sotorasib and KRAS G12C.",
];

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const sseRef = useRef<EventSource | null>(null);
  const [dotCount, setDotCount] = useState(0);

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
        <h1 className="hero-title">OncoGraph</h1>
        <p className="hero-copy">
          Answers oncology questions using knowledge graph backed citations.
        </p>
      </header>

      <section className="card">
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
      </section>

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

      {result && (
        <section className="card result-card">
          <h2 className="section-title">Answer</h2>
          <div className="answer-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown>
          </div>

          <details className="details">
            <summary>Cypher query</summary>
            <pre className="code-block">{result.cypher}</pre>
          </details>

          <details className="details">
            <summary>Result rows</summary>
            <pre className="code-block">{JSON.stringify(result.rows, null, 2)}</pre>
          </details>

          <details className="details" open>
            <summary>Mini graph</summary>
            <div className="graph-container">
              <MiniGraph rows={result.rows} height={360} />
            </div>
          </details>
        </section>
      )}
    </main>
  );
}

