"""Rule-based Cypher validator enforcing read-only safety for the pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import PipelineConfig, PipelineError

FORBIDDEN_KEYWORDS = (
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "REMOVE",
    "CALL",
    "LOAD",
    "DROP",
    "DETACH",
)

ALLOWED_LABELS = {"Gene", "Variant", "Therapy", "Disease", "Biomarker"}
ALLOWED_RELATIONSHIPS = {"VARIANT_OF", "TARGETS", "AFFECTS_RESPONSE_TO"}
ALLOWED_PROPERTIES = {
    # Node properties
    "symbol",
    "hgnc_id",
    "synonyms",
    "name",
    "hgvs_p",
    "consequence",
    "modality",
    "tags",
    "chembl_id",
    "doid",
    # Relationship properties
    "effect",
    "disease_name",
    "disease_id",
    "pmids",
    "source",
    "notes",
}


LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)
NODE_LABEL_PATTERN = re.compile(r"(?<!\[):([A-Za-z_][A-Za-z0-9_]*)")
REL_TYPE_PATTERN = re.compile(r"\[:([A-Za-z_][A-Za-z0-9_]*)")
PROPERTY_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)")


RETURN_CLAUSE_PATTERN = re.compile(r"\bRETURN\b", re.IGNORECASE)


@dataclass
class RuleBasedValidator:
    """Validate Cypher text using simple pattern checks."""

    config: PipelineConfig

    def validate_cypher(self, cypher: str) -> str:
        text = cypher.strip()
        self._check_forbidden_keywords(text)
        self._check_labels(text)
        self._check_relationships(text)
        self._check_properties(text)
        self._ensure_return_clause(text)
        text = self._enforce_limit(text)
        return text

    def _check_forbidden_keywords(self, text: str) -> None:
        upper_text = text.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            pattern = rf"\b{keyword}\b"
            if re.search(pattern, upper_text):
                raise PipelineError(f"Forbidden keyword detected: {keyword}")

    def _check_labels(self, text: str) -> None:
        for match in NODE_LABEL_PATTERN.findall(text):
            if match not in ALLOWED_LABELS:
                raise PipelineError(f"Unknown label: {match}")

    def _check_relationships(self, text: str) -> None:
        for rel in REL_TYPE_PATTERN.findall(text):
            if rel not in ALLOWED_RELATIONSHIPS:
                raise PipelineError(f"Unknown relationship type: {rel}")

    def _ensure_return_clause(self, text: str) -> None:
        if not RETURN_CLAUSE_PATTERN.search(text):
            raise PipelineError("Cypher query must include a RETURN clause")

    def _check_properties(self, text: str) -> None:
        for prop in PROPERTY_PATTERN.findall(text):
            if prop not in ALLOWED_PROPERTIES:
                raise PipelineError(f"Unknown property: {prop}")

    def _enforce_limit(self, text: str) -> str:
        match = LIMIT_PATTERN.search(text)
        if not match:
            return f"{text} LIMIT {self.config.default_limit}"

        limit_value = int(match.group(1))
        if limit_value > self.config.max_limit:
            start, end = match.span(1)
            text = f"{text[:start]}{self.config.max_limit}{text[end:]}"
        return text
