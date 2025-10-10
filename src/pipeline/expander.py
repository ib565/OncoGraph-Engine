"""Simple instruction expander used by the Text-to-Cypher pipeline.

Produces short, schema-aware guidance from a natural-language question.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import InstructionExpander, PipelineError


@dataclass
class SimpleExpander(InstructionExpander):
    """Generate minimal, schema-aware guidance from the user question.

    This adapter deliberately keeps formatting plain-text to match the MVP plan
    and to avoid coupling downstream components to any structured format.
    """

    def expand_instructions(self, question: str) -> str:
        if question is None or not str(question).strip():
            raise PipelineError("Question must be a non-empty string")

        q = question.strip()

        lines: list[str] = [
            "Use the graph labels Gene, Variant, Therapy, Disease (Biomarker helper label).",
            "Unless a disease is named, keep the query tumor-agnostic.",
            "Prefer simple MATCH patterns and return well-named columns.",
            "Return arrays intact (pmids, tags).",
            f"User question: {q}",
        ]
        return "\n".join(lines)
