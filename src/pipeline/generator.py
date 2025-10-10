"""LLM-based Cypher generator for the Text-to-Cypher pipeline.

This adapter accepts plain-text instructions and uses a text-generation client
(LLM) to produce a single Cypher query string. It keeps formatting
requirements strict and performs light extraction/sanitization to return
plain Cypher without code fences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .types import CypherGenerator, PipelineError


class TextGenerationClient(Protocol):
    """Minimal client interface for text generation."""

    def generate(self, prompt: str, *, temperature: float, max_tokens: int) -> str:  # pragma: no cover - interface only
        ...


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that writes safe read-only Cypher for a small oncology knowledge graph.\n"
    "Follow these rules strictly:\n"
    "- Use labels Gene, Variant, Therapy, Disease (Biomarker helper label).\n"
    "- Only MATCH/WHERE/RETURN/ORDER BY/LIMIT are allowed. No procedures.\n"
    "- Preserve deterministic key casing; return well-named columns.\n"
    "- Include a LIMIT (<= 200).\n"
    "- Output only the final Cypher query with no explanation.\n"
)


@dataclass
class LLMBasedGenerator(CypherGenerator):
    """Generate Cypher using a pluggable text generation client."""

    client: TextGenerationClient
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.0
    max_tokens: int = 512

    CODE_FENCE_PATTERN = re.compile(r"```([a-zA-Z]*)\n([\s\S]*?)```", re.MULTILINE)

    def generate_cypher(self, instructions: str) -> str:
        if instructions is None or not str(instructions).strip():
            raise PipelineError("Instructions must be a non-empty string")

        prompt = self._compose_prompt(instructions.strip())
        raw_output = self.client.generate(
            prompt, temperature=self.temperature, max_tokens=self.max_tokens
        )

        cypher = self._extract_cypher(raw_output)
        if not cypher:
            raise PipelineError("LLM returned empty Cypher")

        # Basic guard: forbid obvious non-Cypher boilerplate
        if "\n" not in cypher and not cypher.upper().startswith("MATCH"):
            # Single-line is acceptable but should start with MATCH to be safe
            if not cypher.strip().upper().startswith("MATCH"):
                raise PipelineError("LLM output does not look like Cypher")

        return cypher.strip()

    def _compose_prompt(self, instructions: str) -> str:
        parts = [
            self.system_prompt.rstrip(),
            "\nInstructions (plain text):",
            instructions,
            "\nReturn only the Cypher query. Do not include code fences or explanations.",
        ]
        return "\n".join(parts)

    def _extract_cypher(self, text: str) -> str:
        if text is None:
            return ""
        content = text.strip()

        # If the model provided code fences, extract the inner block
        match = self.CODE_FENCE_PATTERN.search(content)
        if match:
            inner = match.group(2)
            return inner.strip()

        # Otherwise, return the text as-is after removing leading labels
        # like "Cypher:" or "Query:"
        for prefix in ("cypher:", "query:"):
            if content.lower().startswith(prefix):
                return content[len(prefix) :].strip()

        return content
