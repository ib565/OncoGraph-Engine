"""Gemini-powered adapters for instruction expansion, Cypher generation, and summaries."""

from __future__ import annotations

from dataclasses import dataclass

from .prompts import (
    CYPHER_PROMPT_TEMPLATE,
    INSTRUCTION_PROMPT_TEMPLATE,
    SCHEMA_SNIPPET,
    SUMMARY_PROMPT_TEMPLATE,
)
from .types import (
    CypherGenerator,
    InstructionExpander,
    PipelineError,
    Summarizer,
)

try:  # pragma: no cover - optional dependency at runtime
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except ImportError:  # pragma: no cover - handled lazily
    genai = None  # type: ignore
    genai_types = None  # type: ignore


@dataclass(frozen=True)
class GeminiConfig:
    """Runtime settings for Gemini calls."""

    model: str = "gemini-2.5-flash"
    temperature: float = 0.1
    max_output_tokens: int | None = None
    top_p: float | None = None
    api_key: str | None = None


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        body = stripped[3:]
        body = body.lstrip()
        if "\n" in body:
            _, remainder = body.split("\n", 1)
        else:
            remainder = body
        remainder = remainder.rstrip()
        if remainder.endswith("```"):
            remainder = remainder[:-3]
        stripped = remainder.strip()
    return stripped


def _format_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "(no rows)"

    formatted: list[str] = []
    for index, row in enumerate(rows, start=1):
        parts: list[str] = []
        for key, value in row.items():
            if isinstance(value, list):
                joined = ", ".join(str(item) for item in value)
                parts.append(f"{key}: {joined}")
            else:
                parts.append(f"{key}: {value}")
        formatted.append(f"{index}. " + "; ".join(parts))
    return "\n".join(formatted)


class _GeminiBase:
    def __init__(self, config: GeminiConfig | None = None, client: object | None = None) -> None:
        self.config = config or GeminiConfig()
        if client is not None:
            self._client = client
        else:
            if genai is None:  # pragma: no cover - handled in production environment
                raise PipelineError("google-genai package is required for Gemini adapters")
            kwargs: dict[str, object] = {}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._client = genai.Client(**kwargs)  # type: ignore[call-arg]

    def _build_content_config(self) -> object | None:
        if genai_types is None:
            return None
        return genai_types.GenerateContentConfig(  # type: ignore[attr-defined]
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            max_output_tokens=self.config.max_output_tokens,
        )

    def _call_model(self, *, prompt: str) -> str:
        config_payload = self._build_content_config()
        kwargs = {
            "model": self.config.model,
            "contents": [prompt],
        }
        if config_payload is not None:
            kwargs["config"] = config_payload

        response = self._client.models.generate_content(**kwargs)
        text = getattr(response, "text", None)
        if not text:
            raise PipelineError("Gemini response did not include text")
        return text


class GeminiInstructionExpander(_GeminiBase, InstructionExpander):
    """Gemini-backed instruction expansion adapter."""

    def expand_instructions(self, question: str) -> str:
        prompt = INSTRUCTION_PROMPT_TEMPLATE.format(
            schema=SCHEMA_SNIPPET, question=question.strip()
        )
        text = self._call_model(prompt=prompt)
        return text.strip()


class GeminiCypherGenerator(_GeminiBase, CypherGenerator):
    """Gemini-backed Cypher generator adapter."""

    def generate_cypher(self, instructions: str) -> str:
        prompt = CYPHER_PROMPT_TEMPLATE.format(
            schema=SCHEMA_SNIPPET, instructions=instructions.strip()
        )
        text = self._call_model(prompt=prompt)
        return _strip_code_fence(text)


class GeminiSummarizer(_GeminiBase, Summarizer):
    """Gemini-backed summarizer for Cypher results."""

    def summarize(self, question: str, rows: list[dict[str, object]]) -> str:
        formatted_rows = _format_rows(rows)
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            question=question.strip(),
            rows=formatted_rows,
        )
        text = self._call_model(prompt=prompt)
        return text.strip()
