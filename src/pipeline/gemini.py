"""Gemini-powered adapters for instruction expansion, Cypher generation, and summaries."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from .prompts import (
    CYPHER_PROMPT_TEMPLATE,
    ENRICHMENT_SUMMARY_PROMPT_TEMPLATE,
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


class EnrichmentSummaryResponse(BaseModel):
    """Structured response from enrichment summarizer."""

    summary: str
    followUpQuestions: list[str]


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

    @retry(
        retry=retry_if_not_exception_type(PipelineError),  # Retry except PipelineError
        stop=stop_after_attempt(3),  # Maximum 3 attempts
        wait=wait_exponential(multiplier=1, min=1, max=10),  # Exponential backoff
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


class GeminiEnrichmentSummarizer(_GeminiBase):
    """Gemini-backed summarizer for gene enrichment analysis results."""

    def summarize_enrichment(
        self, gene_list: list[str], enrichment_results: list[dict[str, object]], top_n: int = 10
    ) -> EnrichmentSummaryResponse:
        """Generate biological interpretation of enrichment results with follow-up questions.

        Args:
            gene_list: List of genes that were analyzed
            enrichment_results: List of enrichment analysis results

        Returns:
            Structured response with summary and follow-up questions
        """
        # Format enrichment results for the prompt
        formatted_results = []
        for i, result in enumerate(enrichment_results[:top_n], 1):
            formatted_results.append(
                f"{i}. {result['term']} ({result['library']})\n"
                f"Adjusted P-value: {result['adjusted_p_value']:.2e}\n"
                f"   Gene count: {result['gene_count']}\n"
                f"   Genes: {', '.join(result['genes'][:5])}{'...' if len(result['genes']) > 5 else ''}"
            )

        formatted_enrichment = (
            "\n".join(formatted_results)
            if formatted_results
            else "No significant enrichments found"
        )

        prompt = ENRICHMENT_SUMMARY_PROMPT_TEMPLATE.format(
            gene_list=", ".join(gene_list),
            enrichment_results=formatted_enrichment,
            top_n=top_n,
        )

        # Use structured output with Gemini's native JSON mode
        config_payload = self._build_content_config()
        if config_payload is not None:
            # Override the config to include structured output
            config_payload = genai_types.GenerateContentConfig(
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_output_tokens=self.config.max_output_tokens,
                response_mime_type="application/json",
                response_schema=EnrichmentSummaryResponse,
            )

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

        # Parse the JSON response
        try:
            import json

            data = json.loads(text)
            return EnrichmentSummaryResponse(**data)
        except (json.JSONDecodeError, ValueError) as e:
            raise PipelineError(f"Failed to parse structured response: {e}") from e
