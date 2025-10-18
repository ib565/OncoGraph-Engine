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
# Match node labels like (:Gene) or (n:Gene) or (n:Gene:Biomarker), excluding rel brackets
NODE_LABEL_PATTERN = re.compile(r"(?<!\[):\s*`?([A-Za-z_][A-Za-z0-9_]*)`?")
# Match relationship types like [:TYPE], [: TYPE], or [:`TYPE`]
REL_TYPE_PATTERN = re.compile(r"\[\s*:\s*`?([A-Za-z_][A-Za-z0-9_]*)`?")
PROPERTY_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)")


RETURN_CLAUSE_PATTERN = re.compile(r"\bRETURN\b", re.IGNORECASE)


@dataclass
class RuleBasedValidator:
    """Validate Cypher text using simple pattern checks."""

    config: PipelineConfig

    def validate_cypher(self, cypher: str) -> str:
        text = cypher.strip()
        # Disallow parameterized queries (e.g., $GENE). The executor does not
        # provide parameters; require literal inlined strings instead.
        if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", text):
            raise PipelineError(
                "Parameterized queries are not supported; inline literal values (no $parameters)."
            )
        self._check_forbidden_keywords(text)

        # Remove string literals to avoid false positives when scanning for
        # labels, relationship types, and property names (e.g., 'p.G12C').
        scan_text = self._strip_string_literals(text)

        self._check_labels(scan_text)
        self._check_relationships(scan_text)
        self._ensure_return_clause(text)
        text = self._rewrite_case_insensitive(text)
        text = self._enforce_limit(text)
        return text

    def _strip_string_literals(self, text: str) -> str:
        """Return text with contents of single/double-quoted strings removed.

        Handles Cypher-style single quotes and doubled single-quote escapes.
        Double quotes are removed conservatively as well.
        """
        out: list[str] = []
        i = 0
        in_single = False
        in_double = False
        n = len(text)
        while i < n:
            ch = text[i]
            if not in_single and not in_double:
                if ch == "'":
                    in_single = True
                    i += 1
                    continue
                if ch == '"':
                    in_double = True
                    i += 1
                    continue
                out.append(ch)
                i += 1
                continue
            if in_single:
                # Handle doubled single-quote escape inside single-quoted string
                if ch == "'" and i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                if ch == "'":
                    in_single = False
                    i += 1
                    continue
                i += 1
                continue
            # in_double
            if ch == '"':
                in_double = False
                i += 1
                continue
            i += 1
        return "".join(out)

    def _check_forbidden_keywords(self, text: str) -> None:
        upper_text = text.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            pattern = rf"\b{keyword}\b"
            if re.search(pattern, upper_text):
                raise PipelineError(f"Forbidden keyword detected: {keyword}")

    def _check_labels(self, text: str) -> None:
        rel_types = set(REL_TYPE_PATTERN.findall(text))
        for label in NODE_LABEL_PATTERN.findall(text):
            # Skip tokens that are actually relationship types
            if label in ALLOWED_RELATIONSHIPS or label in rel_types:
                continue
            if label not in ALLOWED_LABELS:
                raise PipelineError(f"Unknown label: {label}")

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

    def _rewrite_case_insensitive(self, text: str) -> str:
        """Normalize common equality filters to case-insensitive form.

        Currently targets comparisons of the form:
          <alias>.disease_name = <expr>
        and rewrites to:
          toLower(<alias>.disease_name) = toLower(<expr>)
        """

        def repl(match: re.Match[str]) -> str:
            alias = match.group(1)
            rhs = match.group(2).strip()
            # Ensure closing quote/paren preserved if missing in group
            return f"toLower({alias}.disease_name) = toLower({rhs})"

        pattern = re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\.disease_name\s*=\s*([^\n\r]+?)(?=\s+(?:AND|OR|RETURN|WITH|SKIP|LIMIT|ORDER\b)|$)"
        )
        return pattern.sub(repl, text)
