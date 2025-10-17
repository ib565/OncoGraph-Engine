"use client";

import { useState } from "react";
import MiniGraph from "./components/MiniGraph";

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

    try {
      const response = await fetch(`${API_URL}/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: trimmed }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = payload?.detail;
        if (detail?.message) {
          throw new Error(detail.message);
        }
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = (await response.json()) as QueryResponse;
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
            {isLoading ? "Running…" : "Ask"}
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

      {result && (
        <section className="card result-card">
          <h2 className="section-title">Answer</h2>
          <p className="answer-text">{result.answer}</p>

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

