"""Gemini-powered adapters for instruction expansion, Cypher generation, and summaries."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

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


SCHEMA_SNIPPET = dedent(
    """
    Graph schema:
    - Node labels: Gene(symbol, hgnc_id, synonyms), Variant(name, hgvs_p, consequence, synonyms),
      Therapy(name, modality, tags, chembl_id, synonyms), Disease(name, doid, synonyms)
    - Helper label: Biomarker is applied to Gene and Variant nodes
    - Relationships:
      (Variant)-[:VARIANT_OF]->(Gene)
      (Therapy)-[:TARGETS {source}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {effect, disease_name, disease_id?, pmids, source, notes?}]->(Therapy)
    - Array properties: pmids, tags
    Canonical row return contract:
    RETURN
      CASE WHEN biomarker:Variant THEN coalesce(biomarker.name, biomarker.hgvs_p) END AS variant_name,
      CASE WHEN biomarker:Gene THEN biomarker.symbol ELSE gene.symbol END         AS gene_symbol,
      therapy.name                                                                AS therapy_name,
      rel.effect                                                                  AS effect,
      rel.disease_name                                                            AS disease_name,
      coalesce(rel.pmids, [])                                                     AS pmids
    LIMIT …

    When writing Cypher, ensure the aliases 
    variant_name, gene_symbol, therapy_name, effect, disease_name, pmids are always returned (use CASE/COALESCE so absent values become NULL or []).

    Query patterns (use when applicable):
    - Gene-or-Variant biomarker for generic "<gene> mutations" (prefer this simpler OR form):
      MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (b:Gene AND b.symbol = $GENE)
         OR (b:Variant)-[:VARIANT_OF]->(:Gene {symbol: $GENE})
      // This avoids UNWIND/WITH pitfalls.
      // If you still need to expand nodes, use this UNWIND form (note the list-comprehension filter):
      MATCH (g:Gene {symbol: $GENE})
      OPTIONAL MATCH (v:Variant)-[:VARIANT_OF]->(g)
      WITH g, v
      UNWIND [x IN [g, v] WHERE x IS NOT NULL] AS biomarker_node
      MATCH (biomarker_node:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
    - Therapy class by tags OR TARGETS (case-insensitive for tags):
      MATCH (t:Therapy)
      WHERE any(tag IN t.tags WHERE toLower(tag) CONTAINS toLower($THERAPY_CLASS))
         OR (t)-[:TARGETS]->(:Gene {symbol: $TARGET_GENE})
    - Disease comparisons should be case-insensitive equality; validator will normalize if needed.
    """
).strip()

INSTRUCTION_PROMPT_TEMPLATE = dedent(
    """
    You are an oncology knowledge graph assistant. 
    You provide clear instructions to guide the downstream Cypher generator in forming a valid Cypher query.
    {schema}

    Task: Rewrite the user's question as 3-6 short bullet points that reference the schema labels,
    relationships, and property names. Keep the guidance tumor-agnostic unless a disease is
    explicitly named. Do not produce Cypher or JSON—only plain-text bullet points starting with "- ".

    Guidance:
    - If the question mentions "<gene> mutations" without a specific variant, match the biomarker as the Gene OR any Variant VARIANT_OF that Gene.
    - For therapy classes like "anti-EGFR", match by tags OR by TARGETS to the target Gene.
    - Treat disease matching as case-insensitive equality.

    User question: {question}
    """
).strip()

CYPHER_PROMPT_TEMPLATE = dedent(
    """
    You are generating a single Cypher query for the oncology knowledge graph described below.
    {schema}

    Follow these requirements:
    - Use the provided instruction text exactly once to decide filters, MATCH clauses, and RETURN columns.
    - Produce a single Cypher query with no commentary or markdown fences.
    - Ensure the query includes a RETURN clause with readable column aliases and a LIMIT.
    - If the question names a gene without a specific variant, include biomarker matching for the Gene OR any Variant VARIANT_OF that Gene (prefer the OR form shown in the schema patterns; avoid placing WHERE immediately after UNWIND).
    - For therapy classes (e.g., "anti-EGFR"), allow matching via tags OR via TARGETS to the corresponding Gene.
    - Prefer case-insensitive comparisons for disease names and tags; the validator will normalize simple equality.
    - The RETURN clause MUST project exactly these aliases in order: variant_name, gene_symbol, therapy_name, effect, disease_name, pmids. Use CASE expressions and COALESCE so the columns exist even when values are missing (pmids must always be an array, default to []).

    Instruction text:
    {instructions}
    """
).strip()


SUMMARY_PROMPT_TEMPLATE = dedent(
    """
    You are summarizing query results from an oncology knowledge graph.

    Original question:
    {question}

    Result rows:
    {rows}

    Produce a concise answer in 2-5 sentences. Cite PubMed IDs (PMIDs) inline when available.
    If there are no rows, explicitly state that no evidence was found. Do not invent data.
    """
).strip()


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
