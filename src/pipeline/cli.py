"""Simple CLI to run the end-to-end question → Cypher → answer pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from . import (
    GeminiConfig,
    GeminiCypherGenerator,
    GeminiInstructionExpander,
    GeminiSummarizer,
    Neo4jExecutor,
    PipelineConfig,
    QueryEngine,
    RuleBasedValidator,
)
from .trace import CompositeTraceSink, JsonlTraceSink, StdoutTraceSink, daily_trace_path


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

    trace_path = daily_trace_path(Path("logs") / "traces")

    return QueryEngine(
        config=pipeline_config,
        expander=expander,
        generator=generator,
        validator=validator,
        executor=executor,
        summarizer=summarizer,
        trace=JsonlTraceSink(trace_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run OncoGraph pipeline")
    parser.add_argument("question", nargs="+", help="User question text")
    parser.add_argument("--no-log", action="store_true", help="Disable JSONL logging")
    parser.add_argument(
        "--debug", action="store_true", help="Print stack traces and verbose step output"
    )
    parser.add_argument("--trace", action="store_true", help="Stream trace events to stdout")
    args = parser.parse_args(argv)

    engine = _build_engine()

    if args.trace:
        if engine.trace is None:
            engine.trace = StdoutTraceSink()
        else:
            engine.trace = CompositeTraceSink(engine.trace, StdoutTraceSink())

    question_text = " ".join(args.question).strip()
    started = datetime.now(UTC).isoformat()

    try:
        result = engine.run(question_text)
    except Exception as exc:  # pragma: no cover - surface errors to CLI
        # Print detailed error including step if available
        step = getattr(exc, "step", None)
        if step:
            print(f"Error in step '{step}': {exc}", file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        if args.debug:
            import traceback

            traceback.print_exc()
        if not args.no_log and engine.trace is not None:
            engine.trace.record(
                "error",
                {
                    "started_at": started,
                    "question": question_text,
                    "error": str(exc),
                    "error_step": step or "unknown",
                    "traceback": traceback.format_exc() if args.debug else None,
                },
            )
        return 1

    print("Cypher:\n" + result.cypher + "\n")
    print("Rows:")
    print(json.dumps(result.rows, indent=2))
    print("\nAnswer:\n" + result.answer)

    if not args.no_log and engine.trace is not None:
        engine.trace.record(
            "run",
            {
                "started_at": started,
                "question": question_text,
                "cypher": result.cypher,
                "row_count": len(result.rows),
                "answer": result.answer,
            },
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
