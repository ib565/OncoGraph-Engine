"""Gemini-powered adapters for instruction expansion, Cypher generation, and summaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel

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
from .utils import get_llm_cache, stable_hash

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

    def _call_model(self, *, prompt: str) -> str:
        """Call Gemini API with retry logic and comprehensive error handling."""
        config_payload = self._build_content_config()
        kwargs = {
            "model": self.config.model,
            "contents": [prompt],
        }
        if config_payload is not None:
            kwargs["config"] = config_payload

        # Simple retry loop with exponential backoff
        last_exception = None
        for attempt in range(3):  # 3 attempts total
            try:
                response = self._client.models.generate_content(**kwargs)
                text = getattr(response, "text", None)
                if not text:
                    raise PipelineError("Gemini response did not include text")
                return text
            except Exception as exc:
                last_exception = exc

                # Log detailed error information for each attempt
                error_details = {
                    "attempt": attempt + 1,
                    "total_attempts": 3,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "model": self.config.model,
                    "prompt_length": len(prompt),
                }

                # Extract additional error context
                if hasattr(exc, "details"):
                    error_details["details"] = str(exc.details)
                if hasattr(exc, "code"):
                    error_details["code"] = str(exc.code)
                if hasattr(exc, "status_code"):
                    error_details["status_code"] = str(exc.status_code)
                if hasattr(exc, "reason"):
                    error_details["reason"] = str(exc.reason)

                logging.warning(f"Gemini API call failed: {error_details}")

                # Don't retry on the last attempt
                if attempt == 2:
                    break

                # Wait before retry (exponential backoff: 1s, 2s, 4s)
                import time

                time.sleep(2**attempt)

        # If we get here, all retries failed - preserve the original exception
        if last_exception:
            # Create a comprehensive error message that preserves all details
            error_parts = [
                "Gemini API call failed after 3 attempts",
                f"Exception: {type(last_exception).__name__}",
                f"Message: {str(last_exception)}",
            ]

            # Add specific error details if available
            if hasattr(last_exception, "details") and last_exception.details:
                error_parts.append(f"Details: {last_exception.details}")
            if hasattr(last_exception, "code") and last_exception.code:
                error_parts.append(f"Code: {last_exception.code}")
            if hasattr(last_exception, "status_code") and last_exception.status_code:
                error_parts.append(f"Status: {last_exception.status_code}")
            if hasattr(last_exception, "reason") and last_exception.reason:
                error_parts.append(f"Reason: {last_exception.reason}")

            error_msg = " | ".join(error_parts)

            # Create a PipelineError that preserves the original exception
            pipeline_error = PipelineError(error_msg)
            # Preserve the original exception as the cause
            pipeline_error.__cause__ = last_exception
            raise pipeline_error
        else:
            raise PipelineError("Gemini API call failed for unknown reason")


class GeminiInstructionExpander(_GeminiBase, InstructionExpander):
    """Gemini-backed instruction expansion adapter."""

    def expand_instructions(self, question: str) -> str:
        # Check cache first
        cache = get_llm_cache()
        cache_key = f"expand_instructions:{stable_hash(question.strip())}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        prompt = INSTRUCTION_PROMPT_TEMPLATE.format(schema=SCHEMA_SNIPPET, question=question.strip())
        text = self._call_model(prompt=prompt)
        result = text.strip()

        cache.set(cache_key, result)
        return result


class GeminiCypherGenerator(_GeminiBase, CypherGenerator):
    """Gemini-backed Cypher generator adapter."""

    def generate_cypher(self, instructions: str) -> str:
        # Check cache first
        cache = get_llm_cache()
        cache_key = f"generate_cypher:{stable_hash(instructions.strip())}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        prompt = CYPHER_PROMPT_TEMPLATE.format(schema=SCHEMA_SNIPPET, instructions=instructions.strip())
        text = self._call_model(prompt=prompt)
        result = _strip_code_fence(text)

        cache.set(cache_key, result)
        return result


class GeminiSummarizer(_GeminiBase, Summarizer):
    """Gemini-backed summarizer for Cypher results."""

    def summarize(self, question: str, rows: list[dict[str, object]]) -> str:
        # Check cache first
        cache = get_llm_cache()
        cache_key = f"summarize:{stable_hash(question.strip())}:{stable_hash(rows)}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        formatted_rows = _format_rows(rows)
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            question=question.strip(),
            rows=formatted_rows,
        )
        text = self._call_model(prompt=prompt)
        result = text.strip()

        cache.set(cache_key, result)
        return result


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
        # Check cache first
        cache = get_llm_cache()
        cache_key = f"summarize_enrichment:{stable_hash(sorted(gene_list))}:{top_n}:{stable_hash(enrichment_results)}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct the Pydantic model from the cached dictionary
            if isinstance(cached_result, dict):
                return EnrichmentSummaryResponse(**cached_result)
            return cached_result

        # Format enrichment results for the prompt
        formatted_results = []
        for i, result in enumerate(enrichment_results[:top_n], 1):
            formatted_results.append(
                f"{i}. {result['term']} ({result['library']})\n"
                f"Adjusted P-value: {result['adjusted_p_value']:.2e}\n"
                f"   Gene count: {result['gene_count']}\n"
                f"   Genes: {', '.join(result['genes'][:5])}{'...' if len(result['genes']) > 5 else ''}"
            )

        formatted_enrichment = "\n".join(formatted_results) if formatted_results else "No significant enrichments found"

        prompt = ENRICHMENT_SUMMARY_PROMPT_TEMPLATE.format(
            gene_list=", ".join(gene_list),
            gene_list_count=len(gene_list),
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
            result = EnrichmentSummaryResponse(**data)
            cache.set(cache_key, result)
            return result
        except (json.JSONDecodeError, ValueError) as e:
            raise PipelineError(f"Failed to parse structured response: {e}") from e
