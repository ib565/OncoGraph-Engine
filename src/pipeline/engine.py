"""High-level coordinator for the Text-to-Cypher pipeline."""

from __future__ import annotations

from dataclasses import dataclass

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

        try:
            instructions = self.expander.expand_instructions(question)
            self._trace("expand_instructions", {"question": question, "instructions": instructions})
        except Exception as exc:  # pragma: no cover - defensive
            raise PipelineError("Instruction expansion failed", step="expand_instructions") from exc

        try:
            cypher_draft = self.generator.generate_cypher(instructions)
            self._trace("generate_cypher", {"cypher_draft": cypher_draft})
        except Exception as exc:
            raise PipelineError("Cypher generation failed", step="generate_cypher") from exc

        try:
            cypher = self.validator.validate_cypher(cypher_draft)
            self._trace("validate_cypher", {"cypher": cypher})
        except Exception as exc:
            raise PipelineError("Cypher validation failed", step="validate_cypher") from exc

        try:
            rows = self.executor.execute_read(cypher)
            self._trace("execute_read", {"row_count": len(rows)})
        except Exception as exc:
            raise PipelineError("Cypher execution failed", step="execute_read") from exc

        try:
            answer = self.summarizer.summarize(question, rows)
            self._trace("summarize", {"answer_len": len(answer)})
        except Exception as exc:
            raise PipelineError("Summarization failed", step="summarize") from exc

        return QueryEngineResult(answer=answer, cypher=cypher, rows=rows)
