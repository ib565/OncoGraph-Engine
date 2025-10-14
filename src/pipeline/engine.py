"""High-level coordinator for the Text-to-Cypher pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import logging

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
        # Also emit a simple INFO log for high-level steps
        try:
            logging.getLogger("pipeline.engine").info("%s: %s", step, data)
        except Exception:
            pass

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
