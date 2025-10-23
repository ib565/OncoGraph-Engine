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
    FilteredTraceSink,
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


class GeneSetRequest(BaseModel):
    preset_id: str = Field(..., description="Preset gene set identifier")


class GeneSetResponse(BaseModel):
    genes: list[str]
    description: str


class EnrichmentResponse(BaseModel):
    summary: str
    valid_genes: list[str]
    warnings: list[str]
    enrichment_results: list[dict[str, object]]
    plot_data: dict[str, object]
    followUpQuestions: list[str]


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


@app.post("/graph-gene-sets", response_model=GeneSetResponse)
def get_gene_set(
    body: GeneSetRequest,
    engine: Annotated[QueryEngine, Depends(get_engine)],
) -> GeneSetResponse:
    """Get a preset gene list from the knowledge graph."""

    # Define preset queries
    preset_queries = {
        "colorectal_therapy_genes": {
            "description": "Genes targeted by therapies for Colorectal Cancer",
            "cypher": """
                MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
                WHERE toLower(r.disease_name) CONTAINS 'colorectal'
                OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
                WITH CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol
                WHERE gene_symbol IS NOT NULL
                RETURN DISTINCT gene_symbol
                ORDER BY gene_symbol
                LIMIT 50
            """,
        },
        "lung_therapy_genes": {
            "description": "Genes targeted by therapies for Lung Cancer",
            "cypher": """
                MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
                WHERE toLower(r.disease_name) CONTAINS 'lung'
                OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
                WITH CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol
                WHERE gene_symbol IS NOT NULL
                RETURN DISTINCT gene_symbol
                ORDER BY gene_symbol
                LIMIT 50
            """,
        },
        "resistance_biomarker_genes": {
            "description": "All genes with known resistance biomarkers",
            "cypher": """
                MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
                WHERE toLower(r.effect) = 'resistance'
                OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
                WITH CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol
                WHERE gene_symbol IS NOT NULL
                RETURN DISTINCT gene_symbol
                ORDER BY gene_symbol
                LIMIT 50
            """,
        },
        "egfr_pathway_genes": {
            "description": "Genes targeted by EGFR pathway therapies",
            "cypher": """
                MATCH (t:Therapy)-[r:TARGETS]->(g:Gene)
                WHERE (t)-[:TARGETS]->(:Gene {symbol: 'EGFR'})
                   OR any(tag IN t.tags WHERE toLower(tag) CONTAINS 'anti-egfr')
                   OR any(tag IN t.tags WHERE toLower(tag) CONTAINS 'egfr')
                RETURN DISTINCT g.symbol AS gene_symbol
                ORDER BY gene_symbol
                LIMIT 50
            """,
        },
        "top_biomarker_genes": {
            "description": "Top biomarker genes across all cancers",
            "cypher": """
                MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
                OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
                WITH CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
                     count(r) AS biomarker_count
                WHERE gene_symbol IS NOT NULL
                RETURN gene_symbol, biomarker_count
                ORDER BY biomarker_count DESC, gene_symbol
                LIMIT 50
            """,
        },
    }

    if body.preset_id not in preset_queries:
        available_presets = list(preset_queries.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset_id: {body.preset_id}. Available presets: {available_presets}",
        )

    preset = preset_queries[body.preset_id]

    try:
        # Execute the Cypher query
        rows = engine.executor.execute_read(preset["cypher"].strip())

        # Extract gene symbols from results
        genes = []
        for row in rows:
            if "gene_symbol" in row and row["gene_symbol"]:
                genes.append(str(row["gene_symbol"]))

        return GeneSetResponse(genes=genes, description=preset["description"])

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch gene set: {str(exc)}"
        ) from exc


@app.get("/analyze/genes/stream")
def analyze_genes_stream(
    genes: str, 
    analyzer: Annotated[GeneEnrichmentAnalyzer, Depends(get_enrichment_analyzer)],
    summarizer: Annotated[GeminiEnrichmentSummarizer, Depends(get_enrichment_summarizer)],
) -> StreamingResponse:
    """Server-Sent Events: stream gene enrichment analysis results progressively.

    Events emitted:
      - event: partial, data: {"valid_genes": list, "warnings": list, 
        "enrichment_results": list, "plot_data": dict}
      - event: summary, data: {"summary": str, "followUpQuestions": list}
      - event: error,    data: {"message": str, "step": str | None}
    """
    started = datetime.now(UTC).isoformat()
    started_perf = __import__("time").perf_counter()
    run_id = os.getenv("TRACE_RUN_ID_OVERRIDE") or __import__("uuid").uuid4().hex

    # Set up trace sinks with selective database logging
    trace_sink = JsonlTraceSink(daily_trace_path(Path("logs") / "traces"))

    pg_dsn = os.getenv("TRACE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if pg_dsn:
        # Only log request/response/error events to database
        db_allowed_steps = {"enrichment_request", "enrichment_response", "error"}
        filtered_db_sink = FilteredTraceSink(PostgresTraceSink(pg_dsn), db_allowed_steps)
        trace_sink = CompositeTraceSink(trace_sink, filtered_db_sink)

    trace_stdout_flag = os.getenv("TRACE_STDOUT", "1").strip().lower()
    if trace_stdout_flag in {"1", "true", "yes"}:
        trace_sink = CompositeTraceSink(trace_sink, StdoutTraceSink())

    # Wrap trace with run_id context
    contextual_trace = with_context_trace(trace_sink, {"run_id": run_id})

    # Bridge pipeline trace events into a queue for streaming
    queue_sink = QueueTraceSink()

    # Placeholders to capture the outcome from a background thread
    outcome: dict[str, object] = {"done": False}
    done_event = threading.Event()

    def worker() -> None:
        try:
            # Parse gene list (comma or newline separated)
            gene_symbols = []
            for line in genes.split("\n"):
                gene_symbols.extend([gene.strip() for gene in line.split(",") if gene.strip()])

            if not gene_symbols:
                contextual_trace.record(
                    "error",
                    {
                        "started_at": started,
                        "gene_count": 0,
                        "error": "No valid gene symbols provided",
                        "error_step": "gene_parsing",
                        "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
                    },
                )
                outcome["error"] = {
                    "message": "No valid gene symbols provided", 
                    "step": "gene_parsing"
                }
                return

            # Log initial request
            contextual_trace.record(
                "enrichment_request",
                {
                    "started_at": started,
                    "gene_count": len(gene_symbols),
                    "genes_preview": gene_symbols[:5] if len(gene_symbols) > 5 else gene_symbols,
                },
            )

            # Run gene normalization and enrichment analysis
            step_started = __import__("time").perf_counter()
            try:
                # Pass trace sink to analyzer for detailed logging
                analyzer.trace = contextual_trace
                enrichment_result = analyzer.analyze(gene_symbols)
            except Exception as exc:
                import traceback

                normalization_duration = int(
                    (__import__("time").perf_counter() - step_started) * 1000
                )
                contextual_trace.record(
                    "error",
                    {
                        "started_at": started,
                        "gene_count": len(gene_symbols),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "error_step": "gene_normalization",
                        "duration_ms": normalization_duration,
                        "traceback": traceback.format_exc(),
                    },
                )
                outcome["error"] = {
                    "message": f"Gene normalization failed: {str(exc)}",
                    "error_type": type(exc).__name__,
                    "step": "gene_normalization",
                }
                return

            # Create warnings for invalid genes
            warnings = []
            if enrichment_result.invalid_genes:
                warnings.append(
                    f"Invalid gene symbols (excluded from analysis): "
                    f"{', '.join(enrichment_result.invalid_genes)}"
                )

            if not enrichment_result.valid_genes:
                warnings.append("No valid gene symbols found for analysis")

            # Store partial results for immediate emission
            outcome["partial"] = {
                "valid_genes": enrichment_result.valid_genes,
                "warnings": warnings,
                "enrichment_results": enrichment_result.enrichment_results,
                "plot_data": enrichment_result.plot_data,
            }

            # Generate AI summary with follow-up questions
            step_started = __import__("time").perf_counter()
            try:
                summary_response = summarizer.summarize_enrichment(
                    enrichment_result.valid_genes, enrichment_result.enrichment_results, top_n=7
                )
            except Exception as exc:
                import traceback

                summary_duration = int(
                    (__import__("time").perf_counter() - step_started) * 1000
                )
                contextual_trace.record(
                    "error",
                    {
                        "started_at": started,
                        "gene_count": len(gene_symbols),
                        "valid_genes_count": len(enrichment_result.valid_genes),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "error_step": "ai_summary",
                        "duration_ms": summary_duration,
                        "traceback": traceback.format_exc(),
                    },
                )
                outcome["error"] = {
                    "message": f"AI summary generation failed: {str(exc)}",
                    "error_type": type(exc).__name__,
                    "step": "ai_summary",
                }
                return

            # Store summary results
            outcome["summary"] = {
                "summary": summary_response.summary,
                "followUpQuestions": summary_response.followUpQuestions,
            }

            # Log final response
            total_duration = int(
                (__import__("time").perf_counter() - started_perf) * 1000
            )
            contextual_trace.record(
                "enrichment_response",
                {
                    "started_at": started,
                    "valid_genes_count": len(enrichment_result.valid_genes),
                    "enrichment_results_count": len(enrichment_result.enrichment_results),
                    "warnings_count": len(warnings),
                    "has_plot_data": bool(enrichment_result.plot_data and enrichment_result.plot_data.get("data")),
                    "followup_questions_count": len(summary_response.followUpQuestions),
                    "duration_ms": total_duration,
                },
            )

        except Exception as exc:
            import traceback

            # Log detailed error information
            error_details = {
                "started_at": started,
                "gene_count": len(gene_symbols) if "gene_symbols" in locals() else 0,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "error_step": "enrichment_analysis",
                "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
                "traceback": traceback.format_exc(),
            }

            contextual_trace.record("error", error_details)
            outcome["error"] = {
                "message": f"Gene analysis failed: {str(exc)}",
                "error_type": type(exc).__name__,
                "step": "enrichment_analysis",
            }
        finally:
            outcome["done"] = True
            done_event.set()

    threading.Thread(target=worker, name=f"enrichment-runner-{run_id}", daemon=True).start()

    async def event_stream():  # type: ignore[no-untyped-def]
        # Immediately tell the UI we started
        yield (
            f"event: progress\ndata: "
            f"{json.dumps({'message': 'Normalizing genes and running enrichment analysis'})}\n\n"
        )

        loop = asyncio.get_event_loop()

        def next_payload_blocking() -> dict[str, object] | None:
            try:
                # Use a short timeout to allow periodic checks for completion
                return queue_sink.queue.get(timeout=0.25)
            except Empty:
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
                continue

        # Emit partial results if available
        if "partial" in outcome:
            partial_data = outcome["partial"]  # type: ignore[assignment]
            yield f"event: partial\ndata: {json.dumps(partial_data)}\n\n"

        # Emit summary results if available
        if "summary" in outcome:
            summary_data = outcome["summary"]  # type: ignore[assignment]
            yield f"event: summary\ndata: {json.dumps(summary_data)}\n\n"

        # Emit final error if present
        if "error" in outcome:
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
    started = datetime.now(UTC).isoformat()
    started_perf = __import__("time").perf_counter()
    run_id = os.getenv("TRACE_RUN_ID_OVERRIDE") or __import__("uuid").uuid4().hex

    # Set up trace sinks with selective database logging
    trace_sink = JsonlTraceSink(daily_trace_path(Path("logs") / "traces"))

    pg_dsn = os.getenv("TRACE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if pg_dsn:
        # Only log request/response/error events to database
        db_allowed_steps = {"enrichment_request", "enrichment_response", "error"}
        filtered_db_sink = FilteredTraceSink(PostgresTraceSink(pg_dsn), db_allowed_steps)
        trace_sink = CompositeTraceSink(trace_sink, filtered_db_sink)

    trace_stdout_flag = os.getenv("TRACE_STDOUT", "1").strip().lower()
    if trace_stdout_flag in {"1", "true", "yes"}:
        trace_sink = CompositeTraceSink(trace_sink, StdoutTraceSink())

    # Wrap trace with run_id context
    contextual_trace = with_context_trace(trace_sink, {"run_id": run_id})

    try:
        # Parse gene list (comma or newline separated)
        gene_symbols = []
        for line in body.genes.split("\n"):
            gene_symbols.extend([gene.strip() for gene in line.split(",") if gene.strip()])

        if not gene_symbols:
            contextual_trace.record(
                "error",
                {
                    "started_at": started,
                    "gene_count": 0,
                    "error": "No valid gene symbols provided",
                    "error_step": "gene_parsing",
                    "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
                },
            )
            raise HTTPException(status_code=400, detail="No valid gene symbols provided")

        # Log initial request
        contextual_trace.record(
            "enrichment_request",
            {
                "started_at": started,
                "gene_count": len(gene_symbols),
                "genes_preview": gene_symbols[:5] if len(gene_symbols) > 5 else gene_symbols,
            },
        )

        # Run gene normalization
        step_started = __import__("time").perf_counter()
        try:
            # Pass trace sink to analyzer for detailed logging
            analyzer.trace = contextual_trace
            result = analyzer.analyze(gene_symbols)
        except Exception as exc:
            import traceback

            normalization_duration = int((__import__("time").perf_counter() - step_started) * 1000)
            contextual_trace.record(
                "error",
                {
                    "started_at": started,
                    "gene_count": len(gene_symbols),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "error_step": "gene_normalization",
                    "duration_ms": normalization_duration,
                    "traceback": traceback.format_exc(),
                },
            )
            print(
                f"ERROR in gene normalization: {type(exc).__name__}: {exc}",
                file=__import__("sys").stderr,
            )
            print(f"Traceback:\n{traceback.format_exc()}", file=__import__("sys").stderr)
            raise HTTPException(
                status_code=500,
                detail={
                    "message": f"Gene normalization failed: {str(exc)}",
                    "error_type": type(exc).__name__,
                    "step": "gene_normalization",
                },
            ) from exc
        normalization_duration = int((__import__("time").perf_counter() - step_started) * 1000)

        # Log gene normalization results
        contextual_trace.record(
            "gene_normalization",
            {
                "valid_genes_count": len(result.valid_genes),
                "invalid_genes_count": len(result.invalid_genes),
                "invalid_genes": result.invalid_genes,
                "duration_ms": normalization_duration,
            },
        )

        # Generate AI summary with follow-up questions
        step_started = __import__("time").perf_counter()
        try:
            summary_response = summarizer.summarize_enrichment(
                result.valid_genes, result.enrichment_results, top_n=7
            )
        except Exception as exc:
            import traceback

            summary_duration = int((__import__("time").perf_counter() - step_started) * 1000)
            contextual_trace.record(
                "error",
                {
                    "started_at": started,
                    "gene_count": len(gene_symbols),
                    "valid_genes_count": len(result.valid_genes),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "error_step": "ai_summary",
                    "duration_ms": summary_duration,
                    "traceback": traceback.format_exc(),
                },
            )
            print(
                f"ERROR in AI summary generation: {type(exc).__name__}: {exc}",
                file=__import__("sys").stderr,
            )
            print(f"Traceback:\n{traceback.format_exc()}", file=__import__("sys").stderr)
            raise HTTPException(
                status_code=500,
                detail={
                    "message": f"AI summary generation failed: {str(exc)}",
                    "error_type": type(exc).__name__,
                    "step": "ai_summary",
                },
            ) from exc
        summary_duration = int((__import__("time").perf_counter() - step_started) * 1000)

        # Log AI summary generation
        contextual_trace.record(
            "ai_summary",
            {
                "summary_length": len(summary_response.summary),
                "followup_questions_count": len(summary_response.followUpQuestions),
                "duration_ms": summary_duration,
            },
        )

        # Create warnings for invalid genes
        warnings = []
        if result.invalid_genes:
            warnings.append(
                f"Invalid gene symbols (excluded from analysis): {', '.join(result.invalid_genes)}"
            )

        if not result.valid_genes:
            warnings.append("No valid gene symbols found for analysis")

        # Log final response
        total_duration = int((__import__("time").perf_counter() - started_perf) * 1000)
        contextual_trace.record(
            "enrichment_response",
            {
                "started_at": started,
                "valid_genes_count": len(result.valid_genes),
                "enrichment_results_count": len(result.enrichment_results),
                "warnings_count": len(warnings),
                "has_plot_data": bool(result.plot_data and result.plot_data.get("data")),
                "followup_questions_count": len(summary_response.followUpQuestions),
                "duration_ms": total_duration,
            },
        )

        return EnrichmentResponse(
            summary=summary_response.summary,
            valid_genes=result.valid_genes,
            warnings=warnings,
            enrichment_results=result.enrichment_results,
            plot_data=result.plot_data,
            followUpQuestions=summary_response.followUpQuestions,
        )

    except HTTPException:
        # Re-raise HTTP exceptions without additional logging
        raise
    except Exception as exc:
        # Import traceback for better error reporting
        import traceback

        # Log detailed error information
        error_details = {
            "started_at": started,
            "gene_count": len(gene_symbols) if "gene_symbols" in locals() else 0,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "error_step": "enrichment_analysis",
            "duration_ms": int((__import__("time").perf_counter() - started_perf) * 1000),
            "traceback": traceback.format_exc(),
        }

        contextual_trace.record("error", error_details)

        # Also print to stderr for immediate visibility
        print(
            f"ERROR in enrichment analysis: {type(exc).__name__}: {exc}",
            file=__import__("sys").stderr,
        )
        print(f"Traceback:\n{traceback.format_exc()}", file=__import__("sys").stderr)

        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Gene analysis failed: {str(exc)}",
                "error_type": type(exc).__name__,
                "step": "enrichment_analysis",
            },
        ) from exc
