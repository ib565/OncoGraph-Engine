"""High-level coordinator for the LLM-to-Cypher pipeline."""

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

    def run(self, question: str) -> QueryEngineResult:
        """Execute the pipeline in sequence and return the final answer."""

        try:
            instructions = self.expander.expand_instructions(question)
        except Exception as exc:  # pragma: no cover - defensive
            raise PipelineError("Instruction expansion failed") from exc

        try:
            cypher_draft = self.generator.generate_cypher(instructions)
        except Exception as exc:
            raise PipelineError("Cypher generation failed") from exc

        try:
            cypher = self.validator.validate_cypher(cypher_draft)
        except Exception as exc:
            raise PipelineError("Cypher validation failed") from exc

        try:
            rows = self.executor.execute_read(cypher)
        except Exception as exc:
            raise PipelineError("Cypher execution failed") from exc

        try:
            answer = self.summarizer.summarize(question, rows)
        except Exception as exc:
            raise PipelineError("Summarization failed") from exc

        return QueryEngineResult(answer=answer, cypher=cypher, rows=rows)

