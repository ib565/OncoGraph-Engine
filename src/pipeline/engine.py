"""High-level coordinator for the Text-to-Cypher pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .types import (
    CypherExecutor,
    CypherGenerator,
    CypherValidator,
    InstructionExpander,
    PipelineConfig,
    PipelineError,
    QueryEngineResult,
    Summarizer,
    TraceSink,
)


@dataclass
class QueryEngine:
    """Run the end-to-end question → Cypher → answer pipeline."""

    config: PipelineConfig
    expander: InstructionExpander
    generator: CypherGenerator
    validator: CypherValidator
    executor: CypherExecutor
    summarizer: Summarizer

    trace: TraceSink | None = None

    def _trace(self, step: str, data: dict[str, object]) -> None:
        if self.trace is not None:
            try:
                self.trace.record(step, data)
            except Exception:
                pass

    def run(self, question: str) -> QueryEngineResult:
        """Execute the pipeline in sequence and return the final answer."""

        self._trace("question", {"question": question})
        run_started = perf_counter()

        try:
            step_started = perf_counter()
            instructions = self.expander.expand_instructions(question)
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace(
                "expand_instructions",
                {"question": question, "instructions": instructions, "duration_ms": duration_ms},
            )
        except Exception as exc:  # pragma: no cover - defensive
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace(
                "error",
                {"step": "expand_instructions", "error": str(exc), "duration_ms": duration_ms},
            )
            raise PipelineError(f"Instruction expansion failed: {exc}", step="expand_instructions") from exc

        try:
            step_started = perf_counter()
            cypher_draft = self.generator.generate_cypher(instructions)
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace("generate_cypher", {"cypher_draft": cypher_draft, "duration_ms": duration_ms})
        except Exception as exc:
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace("error", {"step": "generate_cypher", "error": str(exc), "duration_ms": duration_ms})
            raise PipelineError(f"Cypher generation failed: {exc}", step="generate_cypher") from exc

        try:
            step_started = perf_counter()
            cypher = self.validator.validate_cypher(cypher_draft)
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace("validate_cypher", {"cypher": cypher, "duration_ms": duration_ms})
        except Exception as exc:
            self._trace(
                "error",
                {
                    "step": "validate_cypher",
                    "error": str(exc),
                    "cypher_draft": cypher_draft,
                    "duration_ms": int((perf_counter() - step_started) * 1000),
                },
            )
            raise PipelineError(f"Cypher validation failed: {exc}", step="validate_cypher") from exc

        try:
            step_started = perf_counter()
            rows = self.executor.execute_read(cypher)
            rows_preview = rows[:3]
            duration_ms = int((perf_counter() - step_started) * 1000)
            self._trace(
                "execute_read",
                {"row_count": len(rows), "rows_preview": rows_preview, "duration_ms": duration_ms},
            )
        except Exception as exc:
            self._trace(
                "error",
                {
                    "step": "execute_read",
                    "error": str(exc),
                    "cypher": cypher,
                    "duration_ms": int((perf_counter() - step_started) * 1000),
                },
            )
            raise PipelineError(f"Cypher execution failed: {exc}", step="execute_read") from exc

        try:
            step_started = perf_counter()
            answer = self.summarizer.summarize(question, rows)
            step_duration_ms = int((perf_counter() - step_started) * 1000)
            total_duration_ms = int((perf_counter() - run_started) * 1000)
            self._trace(
                "summarize",
                {
                    "answer_len": len(answer),
                    "answer": answer,
                    "duration_ms": step_duration_ms,
                    "total_duration_ms": total_duration_ms,
                },
            )
        except Exception as exc:
            self._trace(
                "error",
                {
                    "step": "summarize",
                    "error": str(exc),
                    "row_count": len(rows),
                    "duration_ms": int((perf_counter() - step_started) * 1000),
                    "total_duration_ms": int((perf_counter() - run_started) * 1000),
                },
            )
            raise PipelineError(f"Summarization failed: {exc}", step="summarize") from exc

        return QueryEngineResult(answer=answer, cypher=cypher, rows=rows)

    def with_trace(self, trace: TraceSink | None) -> QueryEngine:
        """Return a shallow-copied engine instance with a different trace sink.

        This is useful for per-request tracing (e.g., injecting a run_id) while
        reusing the same underlying components.
        """
        return QueryEngine(
            config=self.config,
            expander=self.expander,
            generator=self.generator,
            validator=self.validator,
            executor=self.executor,
            summarizer=self.summarizer,
            trace=trace,
        )
