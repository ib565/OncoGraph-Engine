"""FastAPI wrapper around the OncoGraph query pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from queue import Empty
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pipeline import (
    GeminiConfig,
    GeminiCypherGenerator,
    GeminiEnrichmentSummarizer,
    GeminiInstructionExpander,
    GeminiSummarizer,
    Neo4jExecutor,
    PipelineConfig,
    QueryEngine,
    QueryEngineResult,
    RuleBasedValidator,
)
from pipeline.enrichment import GeneEnrichmentAnalyzer
from pipeline.trace import (
    CompositeTraceSink,
    JsonlTraceSink,
    PostgresTraceSink,
    QueueTraceSink,
    StdoutTraceSink,
    daily_trace_path,
)
from pipeline.types import PipelineError, with_context_trace

load_dotenv()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language oncology question")


class QueryResponse(BaseModel):
    answer: str
    cypher: str
    rows: list[dict[str, object]]


class GeneListRequest(BaseModel):
    genes: str = Field(..., min_length=1, description="Comma or newline separated gene symbols")


class EnrichmentResponse(BaseModel):
    summary: str
    valid_genes: list[str]
    warnings: list[str]
    enrichment_results: list[dict[str, object]]
    plot_data: dict[str, object]


@lru_cache(maxsize=1)
def build_engine() -> QueryEngine:
    config = PipelineConfig()

    gemini_instruction_expander_config = GeminiConfig(
        model=os.getenv("GEMINI_INSTRUCTION_EXPANDER_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_INSTRUCTION_EXPANDER_TEMPERATURE", "0.1")),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )

    gemini_cypher_generator_config = GeminiConfig(
        model=os.getenv("GEMINI_CYPHER_GENERATOR_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_CYPHER_GENERATOR_TEMPERATURE", "0.1")),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )

    gemini_summarizer_config = GeminiConfig(
        model=os.getenv("GEMINI_SUMMARIZER_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_SUMMARIZER_TEMPERATURE", "0.1")),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )

    neo4j_uri = os.getenv("NEO4J_URI", "").strip()
    neo4j_user = os.getenv("NEO4J_USER", "").strip()
    neo4j_password = os.getenv("NEO4J_PASSWORD", "").strip()

    if not neo4j_uri:
        raise RuntimeError("NEO4J_URI is not set; please configure it before starting the API")
    if not neo4j_user:
        raise RuntimeError("NEO4J_USER is not set; please configure it before starting the API")
    if not neo4j_password:
        raise RuntimeError("NEO4J_PASSWORD is not set; please configure it before starting the API")

    executor = Neo4jExecutor(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        config=config,
    )

    # Compose trace sinks: JSONL (local debug) + optional Postgres + optional stdout
    trace_sink = JsonlTraceSink(daily_trace_path(Path("logs") / "traces"))

    pg_dsn = os.getenv("TRACE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if pg_dsn:
        trace_sink = CompositeTraceSink(trace_sink, PostgresTraceSink(pg_dsn))

    trace_stdout_flag = os.getenv("TRACE_STDOUT", "1").strip().lower()
    if trace_stdout_flag in {"1", "true", "yes"}:
        trace_sink = CompositeTraceSink(trace_sink, StdoutTraceSink())

    return QueryEngine(
        config=config,
        expander=GeminiInstructionExpander(config=gemini_instruction_expander_config),
        generator=GeminiCypherGenerator(config=gemini_cypher_generator_config),
        validator=RuleBasedValidator(config=config),
        executor=executor,
        summarizer=GeminiSummarizer(config=gemini_summarizer_config),
        trace=trace_sink,
    )


def get_engine() -> QueryEngine:
    return build_engine()


@lru_cache(maxsize=1)
def get_enrichment_analyzer() -> GeneEnrichmentAnalyzer:
    """Get cached enrichment analyzer instance."""
    return GeneEnrichmentAnalyzer()


@lru_cache(maxsize=1)
def get_enrichment_summarizer() -> GeminiEnrichmentSummarizer:
    """Get cached enrichment summarizer instance."""
    config = GeminiConfig(
        model=os.getenv("GEMINI_SUMMARIZER_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_SUMMARIZER_TEMPERATURE", "0.1")),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )
    return GeminiEnrichmentSummarizer(config=config)


app = FastAPI(title="OncoGraph API", version="0.1.0")

allowed_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", response_model=dict[str, str])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, engine: Annotated[QueryEngine, Depends(get_engine)]) -> QueryResponse:
    started = datetime.now(UTC).isoformat()
    started_perf = __import__("time").perf_counter()
    run_id = os.getenv("TRACE_RUN_ID_OVERRIDE") or __import__("uuid").uuid4().hex

    # Wrap trace with run_id so all events share a common identifier
    traced_engine = engine
    if engine.trace is not None:
        traced_engine = engine.with_trace(with_context_trace(engine.trace, {"run_id": run_id}))

    try:
        result: QueryEngineResult = traced_engine.run(body.question.strip())
    except PipelineError as exc:
        if traced_engine.trace is not None:
            traced_engine.trace.record(
                "error",
                {
                    "started_at": started,
                    "question": body.question.strip(),
                    "error": str(exc),
                    "error_step": exc.step or "unknown",
                    "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
                },
            )
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "step": exc.step}
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        if traced_engine.trace is not None:
            traced_engine.trace.record(
                "error",
                {
                    "started_at": started,
                    "question": body.question.strip(),
                    "error": str(exc),
                    "error_step": "unknown",
                    "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
                },
            )
        raise HTTPException(status_code=500, detail={"message": str(exc)}) from exc

    if traced_engine.trace is not None:
        traced_engine.trace.record(
            "run",
            {
                "started_at": started,
                "question": body.question.strip(),
                "cypher": result.cypher,
                "row_count": len(result.rows),
                "answer": result.answer,
                "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
            },
        )

    return QueryResponse(answer=result.answer, cypher=result.cypher, rows=result.rows)


@app.get("/query/stream")
def query_stream(
    question: str, engine: Annotated[QueryEngine, Depends(get_engine)]
) -> StreamingResponse:
    """Server-Sent Events: stream progress updates and final result.

    Events emitted:
      - event: progress, data: {"message": str}
      - event: result,   data: {"answer": str, "cypher": str, "rows": list[dict]}
      - event: error,    data: {"message": str, "step": str | None}
    """

    run_id = os.getenv("TRACE_RUN_ID_OVERRIDE") or __import__("uuid").uuid4().hex

    # Bridge pipeline trace events into a queue for streaming
    queue_sink = QueueTraceSink()

    traced_engine = engine
    if engine.trace is not None:
        # Inject run_id context and mirror to the queue sink
        contextual = with_context_trace(engine.trace, {"run_id": run_id})
        composite = CompositeTraceSink(contextual, queue_sink)
        traced_engine = engine.with_trace(composite)
    else:
        traced_engine = engine.with_trace(queue_sink)

    # Placeholders to capture the outcome from a background thread
    outcome: dict[str, object] = {"done": False}
    done_event = threading.Event()

    def worker() -> None:
        try:
            result: QueryEngineResult = traced_engine.run(question.strip())
            outcome["result"] = result
        except PipelineError as exc:
            outcome["error"] = {"message": str(exc), "step": exc.step}
        except Exception as exc:  # pragma: no cover - defensive
            outcome["error"] = {"message": str(exc), "step": "unknown"}
        finally:
            outcome["done"] = True
            done_event.set()

    threading.Thread(target=worker, name=f"query-runner-{run_id}", daemon=True).start()

    async def event_stream():  # type: ignore[no-untyped-def]
        # Immediately tell the UI we started
        yield f"event: progress\ndata: {json.dumps({'message': 'Expanding the Query'})}\n\n"

        loop = asyncio.get_event_loop()
        last_emitted: set[str] = set()

        def next_payload_blocking() -> dict[str, object] | None:
            try:
                # Use a short timeout to allow periodic checks for completion
                return queue_sink.queue.get(timeout=0.25)
            except Empty:
                return None

        def map_step_to_message(step: str) -> str | None:
            if step == "expand_instructions" and "generating" not in last_emitted:
                last_emitted.add("generating")
                return "Generating Cypher"
            if step == "generate_cypher" and "validating" not in last_emitted:
                last_emitted.add("validating")
                return "Validating and Executing Cypher"
            if step == "execute_read" and "summarizing" not in last_emitted:
                last_emitted.add("summarizing")
                return "Summarizing Results"
            return None

        while not done_event.is_set() or not queue_sink.queue.empty():
            payload = await loop.run_in_executor(None, next_payload_blocking)
            if not payload:
                # heartbeat to keep connection alive
                yield ": keep-alive\n\n"
                continue

            step = str(payload.get("step", ""))
            if step == "error":
                error_message = str(payload.get("error", ""))
                error_step = str(payload.get("step", "unknown"))
                error_payload = {"message": error_message, "step": error_step}
                yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
                # Do not break; wait for thread outcome to finish
                continue

            message = map_step_to_message(step)
            if message:
                yield f"event: progress\ndata: {json.dumps({'message': message})}\n\n"

        # Emit the final result or error
        if "result" in outcome:
            res: QueryEngineResult = outcome["result"]  # type: ignore[assignment]
            data = {"answer": res.answer, "cypher": res.cypher, "rows": res.rows}
            yield f"event: result\ndata: {json.dumps(data)}\n\n"
        elif "error" in outcome:
            err = outcome["error"]  # type: ignore[assignment]
            yield f"event: error\ndata: {json.dumps(err)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # hint for some proxies (e.g., nginx)
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.post("/analyze/genes", response_model=EnrichmentResponse)
def analyze_genes(
    body: GeneListRequest,
    analyzer: Annotated[GeneEnrichmentAnalyzer, Depends(get_enrichment_analyzer)],
    summarizer: Annotated[GeminiEnrichmentSummarizer, Depends(get_enrichment_summarizer)],
) -> EnrichmentResponse:
    """Analyze gene list for functional enrichment and generate AI summary."""
    try:
        # Parse gene list (comma or newline separated)
        gene_symbols = []
        for line in body.genes.split("\n"):
            gene_symbols.extend([gene.strip() for gene in line.split(",") if gene.strip()])

        if not gene_symbols:
            raise HTTPException(status_code=400, detail="No valid gene symbols provided")

        # Run enrichment analysis
        result = analyzer.analyze(gene_symbols)

        # Generate AI summary
        summary = summarizer.summarize_enrichment(result.valid_genes, result.enrichment_results)

        # Create warnings for invalid genes
        warnings = []
        if result.invalid_genes:
            warnings.append(
                f"Invalid gene symbols (excluded from analysis): {', '.join(result.invalid_genes)}"
            )

        if not result.valid_genes:
            warnings.append("No valid gene symbols found for analysis")

        return EnrichmentResponse(
            summary=summary,
            valid_genes=result.valid_genes,
            warnings=warnings,
            enrichment_results=result.enrichment_results,
            plot_data=result.plot_data,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gene analysis failed: {str(exc)}") from exc
