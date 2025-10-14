"""FastAPI wrapper around the OncoGraph query pipeline."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from pipeline.trace import (
    CompositeTrace,
    JsonlTraceSink,
    LoggingTraceSink,
    get_daily_trace_path,
    init_logging,
    set_global_trace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

load_dotenv()
init_logging()

from pipeline import (
    GeminiConfig,
    GeminiCypherGenerator,
    GeminiInstructionExpander,
    GeminiSummarizer,
    Neo4jExecutor,
    PipelineConfig,
    QueryEngine,
    QueryEngineResult,
    RuleBasedValidator,
)
from pipeline.types import PipelineError


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language oncology question")


class QueryResponse(BaseModel):
    answer: str
    cypher: str
    rows: list[dict[str, object]]


@lru_cache(maxsize=1)
def build_engine() -> QueryEngine:
    config = PipelineConfig()

    gemini_config = GeminiConfig(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
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

    engine = QueryEngine(
        config=config,
        expander=GeminiInstructionExpander(config=gemini_config),
        generator=GeminiCypherGenerator(config=gemini_config),
        validator=RuleBasedValidator(config=config),
        executor=executor,
        summarizer=GeminiSummarizer(config=gemini_config),
    )

    # Enable step-by-step console logs and JSONL traces for UI runs
    sinks = [LoggingTraceSink(), JsonlTraceSink(get_daily_trace_path())]
    engine.trace = CompositeTrace(*sinks)
    set_global_trace(engine.trace)
    return engine


def get_engine() -> QueryEngine:
    return build_engine()


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
def query(body: QueryRequest, engine: QueryEngine = Depends(get_engine)) -> QueryResponse:
    try:
        result: QueryEngineResult = engine.run(body.question.strip())
    except PipelineError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "step": exc.step}
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=500, detail={"message": str(exc)}) from exc

    return QueryResponse(answer=result.answer, cypher=result.cypher, rows=result.rows)
