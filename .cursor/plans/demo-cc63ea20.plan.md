<!-- cc63ea20-714f-4fb2-add6-4ce8d5b0ce15 7c5fd8d9-8c4c-4794-bbbe-853f2d74071d -->
# Demo-Ready Deployment Plan (Render + Vercel + Aura)

## Goal

Deliver a minimal, polished demo UI that calls a FastAPI backend which wraps the existing `QueryEngine`, using Neo4j Aura as the data source. Prioritize clean UX and reliability; add fallbacks/tests after demo.

## What We’ll Reuse (Key Anchors)

- `QueryEngine.run(question)` orchestrates expand → generate → validate → execute → summarize:
```40:98:src/pipeline/engine.py
def run(self, question: str) -> QueryEngineResult:
    """Execute the pipeline in sequence and return the final answer."""

    self._trace("question", {"question": question})

    try:
        instructions = self.expander.expand_instructions(question)
        self._trace("expand_instructions", {"question": question, "instructions": instructions})
    except Exception as exc:  # pragma: no cover - defensive
        self._trace("error", {"step": "expand_instructions", "error": str(exc)})
        raise PipelineError(
            f"Instruction expansion failed: {exc}", step="expand_instructions"
        ) from exc

    try:
        cypher_draft = self.generator.generate_cypher(instructions)
        self._trace("generate_cypher", {"cypher_draft": cypher_draft})
    except Exception as exc:
        self._trace("error", {"step": "generate_cypher", "error": str(exc)})
        raise PipelineError(f"Cypher generation failed: {exc}", step="generate_cypher") from exc

    try:
        cypher = self.validator.validate_cypher(cypher_draft)
        self._trace("validate_cypher", {"cypher": cypher})
    except Exception as exc:
        self._trace(
            "error",
            {"step": "validate_cypher", "error": str(exc), "cypher_draft": cypher_draft},
        )
        raise PipelineError(f"Cypher validation failed: {exc}", step="validate_cypher") from exc

    try:
        rows = self.executor.execute_read(cypher)
        rows_preview = rows[:3]
        self._trace(
            "execute_read",
            {"row_count": len(rows), "rows_preview": rows_preview},
        )
    except Exception as exc:
        self._trace(
            "error",
            {"step": "execute_read", "error": str(exc), "cypher": cypher},
        )
        raise PipelineError(f"Cypher execution failed: {exc}", step="execute_read") from exc

    try:
        answer = self.summarizer.summarize(question, rows)
        self._trace(
            "summarize",
            {"answer_len": len(answer), "answer": answer},
        )
    except Exception as exc:
        self._trace(
            "error",
            {"step": "summarize", "error": str(exc), "row_count": len(rows)},
        )
        raise PipelineError(f"Summarization failed: {exc}", step="summarize") from exc

    return QueryEngineResult(answer=answer, cypher=cypher, rows=rows)
```

- How we build the engine today (we’ll mirror this in the API):
```35:73:src/pipeline/cli.py
def _build_engine() -> QueryEngine:
    load_dotenv()

    pipeline_config = PipelineConfig()

    gemini_config = GeminiConfig(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )

    expander = GeminiInstructionExpander(config=gemini_config)
    generator = GeminiCypherGenerator(config=gemini_config)
    validator = RuleBasedValidator(config=pipeline_config)

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    executor = Neo4jExecutor(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        config=pipeline_config,
    )

    summarizer = GeminiSummarizer(config=gemini_config)

    trace_path = Path("logs/traces/") / (datetime.now(UTC).strftime("%Y%m%d") + ".jsonl")

    return QueryEngine(
        config=pipeline_config,
        expander=expander,
        generator=generator,
        validator=validator,
        executor=executor,
        summarizer=summarizer,
        trace=JsonlTraceSink(trace_path),
    )
```

- Neo4j read path (works with Aura `neo4j+s://…`):
```53:69:src/pipeline/executor.py
def execute_read(self, cypher: str) -> list[dict[str, object]]:
    try:
        with self._driver.session() as session:
            return session.execute_read(self._run_query, cypher)
    except Exception as exc:  # pragma: no cover - defensive
        raise PipelineError(
            f"Neo4j execution failed: {type(exc).__name__}: {exc}", step="execute_read"
        ) from exc

def _run_query(self, tx: Session, cypher: str) -> list[dict[str, object]]:
    result = tx.run(
        cypher,
        timeout=self.config.neo4j_timeout_seconds,
        fetch_size=self.config.neo4j_fetch_size,
    )
    rows = [record.data() for record in result]
    return [_normalize_row(row) for row in rows]
```


## Backend API (FastAPI on Render)

- Create `api/main.py` with two routes:
  - `GET /healthz` → `{status:"ok"}`
  - `POST /query` → body `{question:string}`; returns `{answer, cypher, rows}` by calling `QueryEngine.run()`
- Build the engine inside the app startup using the same config as CLI, reading env: `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_TEMPERATURE`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
- Add CORS for the Vercel domain (env `CORS_ORIGINS=https://<your-vercel-app>.vercel.app`).
- Log to stdout; keep JSONL trace writing as-is (optional in server), but do not block on I/O.
- Minimal pydantic model for input validation.

Minimal skeleton:

```python
# api/main.py (essential sketch)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from pipeline import (
    GeminiConfig, GeminiCypherGenerator, GeminiInstructionExpander,
    GeminiSummarizer, Neo4jExecutor, PipelineConfig, QueryEngine, RuleBasedValidator,
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg = PipelineConfig()
llm = GeminiConfig(
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
    api_key=os.getenv("GOOGLE_API_KEY"),
)
engine = QueryEngine(
    config=cfg,
    expander=GeminiInstructionExpander(llm),
    generator=GeminiCypherGenerator(llm),
    validator=RuleBasedValidator(cfg),
    executor=Neo4jExecutor(
        uri=os.getenv("NEO4J_URI"),
        user=os.getenv("NEO4J_USER"),
        password=os.getenv("NEO4J_PASSWORD"),
        config=cfg,
    ),
    summarizer=GeminiSummarizer(llm),
    trace=None,
)

class QueryIn(BaseModel):
    question: str

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.post("/query")
def query(body: QueryIn):
    r = engine.run(body.question)
    return {"answer": r.answer, "cypher": r.cypher, "rows": r.rows}
```

Dependencies to add in `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic>=2.0`.

Render deploy:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Env: `GOOGLE_API_KEY`, `NEO4J_URI=neo4j+s://<id>.databases.neo4j.io`, `NEO4J_USER`, `NEO4J_PASSWORD`, `CORS_ORIGINS=https://<vercel-app>.vercel.app`

## Neo4j Aura Seeding

- Use the existing builder with Aura creds to ingest CSVs:
```190:196:src/graph/builder.py
if __name__ == "__main__":

    builder = OncoGraphBuilder()
    builder.run_ingestion()
    print("\nDone.")
    builder.close()
```


Steps:

1) From your laptop, set env to Aura (URI `neo4j+s://...`, username/password from Aura console).

2) Run: `python -m src.graph.builder`

3) Verify counts in Aura Browser (constraints exist; a few hundred nodes/edges from CSVs).

## Frontend UI (Next.js on Vercel)

- Create a minimal Next.js app (App Router). Add a single page with:
  - Text input + submit
  - Answer section; collapsible details for Cypher and Rows
  - Optional: small inline graph later (Cytoscape) — defer if time is tight
- Read `NEXT_PUBLIC_API_URL` (Render URL) and `POST /query`.

Minimal page sketch:

```tsx
// app/page.tsx
'use client';
import { useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL!;

export default function Home() {
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault(); setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_URL}/query`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setResp(await r.json());
    } catch (err: any) {
      setError(err.message);
    } finally { setLoading(false); }
  }

  return (
    <main style={{maxWidth:800, margin:'2rem auto', padding:'0 1rem'}}>
      <form onSubmit={onSubmit} style={{display:'flex', gap:8}}>
        <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Ask about biomarkers and therapies…" style={{flex:1}} />
        <button disabled={loading || !q.trim()}>Ask</button>
      </form>
      {error && <p style={{color:'red'}}>Error: {error}</p>}
      {resp && (
        <section>
          <h3>Answer</h3>
          <p>{resp.answer}</p>
          <details><summary>Cypher</summary><pre>{resp.cypher}</pre></details>
          <details><summary>Rows</summary><pre>{JSON.stringify(resp.rows, null, 2)}</pre></details>
        </section>
      )}
    </main>
  );
}
```

Vercel deploy:

- Set Project Root to the Next.js app directory
- Env: `NEXT_PUBLIC_API_URL=https://<your-render-service>.onrender.com`

## Smoke Tests (manual)

- KRAS–Cetuximab (colorectal), BRAF V600E–Vemurafenib (melanoma), KRAS G12C–Sotorasib (lung)
- Expect: non-empty rows, succinct answer, pmids present when available

## Post-Demo Backlog (deferred)

- One-pass zero-row fallback in `QueryEngine.run` (relax filters); instrument trace with fallback metadata
- Cached regression suite with stubbed LLM responses
- Optional LangSmith spans around Gemini calls; keep JSONL logs

### To-dos

- [ ] Add FastAPI/uvicorn/pydantic to requirements.txt
- [ ] Create FastAPI app in api/main.py with /query and CORS
- [ ] Deploy API to Render with env vars and start command
- [ ] Seed Neo4j Aura with CSVs using src/graph/builder.py
- [ ] Create minimal Next.js UI with Q&A and details panels
- [ ] Deploy UI to Vercel and set NEXT_PUBLIC_API_URL
- [ ] Run three manual queries and verify outputs