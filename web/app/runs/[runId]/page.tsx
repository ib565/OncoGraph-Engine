"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MiniGraph from "../../components/MiniGraph";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

type RunData = {
  run_id: string;
  run_type: "query" | "enrichment";
  question?: string;
  genes?: string;
  cypher?: string;
  row_count?: number;
  answer?: string;
  summary?: string;
  enrichment_results?: Array<Record<string, unknown>>;
  plot_data?: Record<string, unknown>;
  duration_ms: number;
  started_at: string;
  model: string;
};

export default function RunPage() {
  const params = useParams();
  const runId = params.runId as string;
  const [runData, setRunData] = useState<RunData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchRun = async () => {
      try {
        const response = await fetch(`${API_URL}/runs/${runId}`);
        if (!response.ok) {
          if (response.status === 404) {
            setError("Run not found");
          } else {
            setError(`Failed to load run: ${response.statusText}`);
          }
          return;
        }
        const data = await response.json();
        setRunData(data);
      } catch (err) {
        setError(`Error loading run: ${err instanceof Error ? err.message : "Unknown error"}`);
      } finally {
        setLoading(false);
      }
    };

    if (runId) {
      fetchRun();
    }
  }, [runId]);

  if (loading) {
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        <p>Loading run...</p>
      </div>
    );
  }

  if (error || !runData) {
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        <h1>Run Not Found</h1>
        <p>{error || "The requested run could not be found."}</p>
      </div>
    );
  }

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatDate = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  };

  return (
    <div style={{ padding: "2rem", maxWidth: "1200px", margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: "2rem", paddingBottom: "1rem", borderBottom: "1px solid #e0e0e0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", marginBottom: "0.5rem" }}>
          <h1 style={{ margin: 0 }}>Shared Run</h1>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <span
              style={{
                fontSize: "0.75rem",
                padding: "0.25rem 0.5rem",
                backgroundColor: "#e3f2fd",
                color: "#1976d2",
                borderRadius: "4px",
                fontWeight: "500",
              }}
            >
              Model: {runData.model}
            </span>
            <span
              style={{
                fontSize: "0.75rem",
                padding: "0.25rem 0.5rem",
                backgroundColor: "#f5f5f5",
                color: "#666",
                borderRadius: "4px",
              }}
            >
              {formatDuration(runData.duration_ms)}
            </span>
          </div>
        </div>
        <p style={{ margin: 0, color: "#666", fontSize: "0.875rem" }}>
          Run ID: <code style={{ fontSize: "0.875rem" }}>{runData.run_id}</code> • {formatDate(runData.started_at)}
        </p>
      </div>

      {/* Query Run */}
      {runData.run_type === "query" && (
        <>
          <div style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Question</h2>
            <p style={{ fontSize: "1rem", color: "#333", padding: "1rem", backgroundColor: "#f9f9f9", borderRadius: "4px" }}>
              {runData.question}
            </p>
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Answer</h2>
            <div style={{ padding: "1rem", backgroundColor: "#f9f9f9", borderRadius: "4px" }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{runData.answer || "No answer available"}</ReactMarkdown>
            </div>
          </div>

          {runData.cypher && (
            <div style={{ marginBottom: "1.5rem" }}>
              <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Cypher Query</h2>
              <pre
                style={{
                  padding: "1rem",
                  backgroundColor: "#f5f5f5",
                  borderRadius: "4px",
                  overflow: "auto",
                  fontSize: "0.875rem",
                  lineHeight: "1.5",
                }}
              >
                {runData.cypher}
              </pre>
            </div>
          )}

          {runData.row_count !== undefined && (
            <p style={{ color: "#666", fontSize: "0.875rem", marginBottom: "1.5rem" }}>
              {runData.row_count} result{runData.row_count !== 1 ? "s" : ""}
            </p>
          )}
        </>
      )}

      {/* Enrichment Run */}
      {runData.run_type === "enrichment" && (
        <>
          <div style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Genes Analyzed</h2>
            <p style={{ fontSize: "1rem", color: "#333", padding: "1rem", backgroundColor: "#f9f9f9", borderRadius: "4px" }}>
              {runData.genes || "No genes specified"}
            </p>
          </div>

          {runData.summary && (
            <div style={{ marginBottom: "1.5rem" }}>
              <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Summary</h2>
              <div style={{ padding: "1rem", backgroundColor: "#f9f9f9", borderRadius: "4px" }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{runData.summary}</ReactMarkdown>
              </div>
            </div>
          )}

          {runData.enrichment_results && runData.enrichment_results.length > 0 && (
            <div style={{ marginBottom: "1.5rem" }}>
              <h2 style={{ fontSize: "1.125rem", marginBottom: "0.5rem" }}>Enrichment Results</h2>
              <div style={{ padding: "1rem", backgroundColor: "#f9f9f9", borderRadius: "4px" }}>
                <p style={{ fontSize: "0.875rem", color: "#666", marginBottom: "1rem" }}>
                  {runData.enrichment_results.length} enriched pathway{runData.enrichment_results.length !== 1 ? "s" : ""}
                </p>
                {/* You can add more detailed enrichment display here */}
              </div>
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: "2rem", paddingTop: "1rem", borderTop: "1px solid #e0e0e0", textAlign: "center" }}>
        <a href="/" style={{ color: "#1976d2", textDecoration: "none" }}>
          ← Back to OncoGraph
        </a>
      </div>
    </div>
  );
}

