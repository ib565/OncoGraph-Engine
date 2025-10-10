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


class JsonlTraceSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, step: str, data: dict[str, object]) -> None:  # pragma: no cover - simple IO
        payload = {"timestamp": datetime.now(UTC).isoformat(), "step": step, **data}
        _log_trace(self._path, payload)


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


def _log_trace(output_path: Path, payload: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run OncoGraph pipeline")
    parser.add_argument("question", nargs="+", help="User question text")
    parser.add_argument("--no-log", action="store_true", help="Disable JSONL logging")
    args = parser.parse_args(argv)

    engine = _build_engine()

    question_text = " ".join(args.question).strip()
    started = datetime.now(UTC).isoformat()

    try:
        result = engine.run(question_text)
    except Exception as exc:  # pragma: no cover - surface errors to CLI
        print(f"Error: {exc}", file=sys.stderr)
        if not args.no_log:
            trace_path = Path("logs/traces/") / (datetime.now(UTC).strftime("%Y%m%d") + ".jsonl")
            _log_trace(
                trace_path,
                {
                    "timestamp": started,
                    "step": "error",
                    "question": question_text,
                    "error": str(exc),
                },
            )
        return 1

    print("Cypher:\n" + result.cypher + "\n")
    print("Rows:")
    print(json.dumps(result.rows, indent=2))
    print("\nAnswer:\n" + result.answer)

    if not args.no_log:
        trace_path = Path("logs/traces/") / (datetime.utcnow().strftime("%Y%m%d") + ".jsonl")
        _log_trace(
            trace_path,
            {
                "timestamp": started,
                "step": "run",
                "question": question_text,
                "cypher": result.cypher,
                "row_count": len(result.rows),
            },
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
