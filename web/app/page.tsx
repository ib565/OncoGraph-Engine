"use client";

import { useState } from "react";

type QueryResponse = {
  answer: string;
  cypher: string;
  rows: Array<Record<string, unknown>>;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) {
      return;
    }

    if (!API_URL) {
      setError("NEXT_PUBLIC_API_URL is not configured");
      return;
    }

    setIsLoading(true);
    setError(null);

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
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ marginBottom: "0.5rem", fontSize: "2.25rem" }}>OncoGraph Demo</h1>
        <p style={{ margin: 0, color: "#4b5563" }}>
          Ask oncology biomarker questions; we translate to Cypher and summarize real graph data.
        </p>
      </header>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.75rem", marginBottom: "1.5rem" }}>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Do KRAS mutations affect response to anti-EGFR therapy in colorectal cancer?"
          style={{ flex: 1, padding: "0.85rem 1rem", borderRadius: "0.75rem", border: "1px solid #d1d5db" }}
        />
        <button
          type="submit"
          disabled={isLoading || !question.trim()}
          style={{
            backgroundColor: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: "0.75rem",
            padding: "0.85rem 1.75rem",
            fontWeight: 600,
            opacity: isLoading || !question.trim() ? 0.7 : 1,
          }}
        >
          {isLoading ? "Running…" : "Ask"}
        </button>
      </form>

      {error && (
        <div
          style={{
            backgroundColor: "#fee2e2",
            color: "#b91c1c",
            padding: "1rem 1.25rem",
            borderRadius: "0.75rem",
            marginBottom: "1.5rem",
          }}
        >
          {error}
        </div>
      )}

      {result && (
        <section
          style={{
            backgroundColor: "white",
            borderRadius: "0.75rem",
            padding: "1.75rem",
            boxShadow: "0 1px 2px rgba(15, 23, 42, 0.08)",
            border: "1px solid #e5e7eb",
          }}
        >
          <h2 style={{ marginTop: 0 }}>Answer</h2>
          <p style={{ lineHeight: 1.6, fontSize: "1.05rem" }}>{result.answer}</p>

          <details style={{ marginTop: "1.5rem" }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Cypher query</summary>
            <pre
              style={{
                backgroundColor: "#0f172a",
                color: "#f8fafc",
                padding: "1rem",
                borderRadius: "0.75rem",
                overflowX: "auto",
                marginTop: "0.75rem",
              }}
            >
              {result.cypher}
            </pre>
          </details>

          <details style={{ marginTop: "1.5rem" }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Result rows</summary>
            <pre
              style={{
                backgroundColor: "#111827",
                color: "#f9fafb",
                padding: "1rem",
                borderRadius: "0.75rem",
                overflowX: "auto",
                marginTop: "0.75rem",
              }}
            >
              {JSON.stringify(result.rows, null, 2)}
            </pre>
          </details>
        </section>
      )}
    </main>
  );
}

