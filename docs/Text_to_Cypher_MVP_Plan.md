# Text→Cypher MVP Plan

## Scope and Principles
- **Text-only LLM outputs**: keep prompts flexible; no structured JSON enforcement.
- **Tumor-agnostic by default**: only add disease filters when the user explicitly names one.
- **Read-only Cypher**: enforce strict validation with sensible default limits and timeouts.
- **Minimal logging surface**: capture every LLM step in local JSONL and LangSmith traces.
- **Modular adapters**: design interchangeable components, keeping the door open for LangChain `GraphCypherQAChain`.

## End-to-End Flow
1. **User query** → raw text input.
2. **Instruction expansion** (Gemini): generate schema-aware, plain-text guidance aligned with graph terminology.
3. **Cypher generation** (Gemini): transform instructions into a single Cypher query.
4. **Safety validation**: allowlist read-only clauses, inject a default `LIMIT` when missing, and reject unknown schema elements.
5. **Execute** (Neo4j): run read-only with a reasonable timeout; return rows as dictionaries. `pmids` and `tags` remain lists.
6. **Summarize** (Gemini): produce a concise answer using the original question and the result rows.

## Schema Grounding
- **Node labels & properties**
  - `Gene(symbol, hgnc_id, synonyms)`
  - `Variant(name, hgvs_p, consequence, synonyms)`
  - `Therapy(name, modality, tags, chembl_id, synonyms)`
  - `Disease(name, doid, synonyms)`
  - Helper label: `Biomarker` (applied to `Gene` and `Variant`)
- **Relationships**
  - `(Variant)-[:VARIANT_OF]->(Gene)`
  - `(Therapy)-[:TARGETS {source}]->(Gene)`
  - `(Biomarker)-[:AFFECTS_RESPONSE_TO {effect, disease_name, disease_id?, pmids, source, notes?}]->(Therapy)`
- **List fields**: `pmids` and `tags` are stored as arrays (semicolon-split during ingest).

## Prompting Guidelines (Plain Text)
- **Instruction expansion**
  - Ground steps in the labels (`Gene`, `Variant`, `Therapy`, `Disease`, `Biomarker`) and relationships above.
  - Use exact property names (`name`, `symbol`, `tags`, `effect`, `disease_name`, `pmids`).
  - Unless a disease is named, keep queries tumor-agnostic.
  - Output a short list of actions or filters.
- **Cypher generation**
  - Feed the instruction text plus a schema snippet to produce Cypher only (no prose).
  - Prefer case-insensitive comparisons for names/tags where appropriate.
  - Ensure final query returns well-named columns (`variant_name`, `gene_symbol`, `therapy_name`, `effect`, `disease_name`, `pmids`) and includes a `LIMIT`.
- **Summarization**
  - Inputs: original question and the result rows (nothing else).
  - Output: 2–5 sentences, explicitly citing PMIDs when present; report “no evidence found” if rows are empty.

## Safety Validation Rules
- **Allowlist clauses**: `MATCH`, `OPTIONAL MATCH`, `WHERE`, `WITH`, `RETURN`, `ORDER BY`, `LIMIT`, `SKIP`, `UNWIND`, `COLLECT`.
- **Block entirely**: `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `CALL` (incl. APOC), `LOAD CSV`, transaction keywords, schema operations.
- **Limit enforcement**: auto-append `LIMIT 100` when absent; cap user-provided limits at 200.
- **Schema checks**: verify all labels, relationship types, and property names against this plan/README/CSV headers.
- **Optional repair loop**: attempt `EXPLAIN` and allow a single LLM self-correction using only the error message.

## Execution Defaults
- Use Neo4j `execute_read` with a ~15s timeout and tuned `fetch_size` for small graphs.
- Normalize array fields (`pmids`, `tags`) into Python lists before passing to the summarizer.
- Preserve deterministic key casing in result dictionaries.

## Logging & Tracing
- **Local JSONL**: `logs/traces/YYYYMMDD.jsonl`, with `timestamp`, `session_id`, `step`, `model`, `prompt_version`, `input_text` / `result_rows`, `output_text` / `cypher`, `latency_ms`, `token_usage` (if available), `row_count`, `error`.
- **LangSmith**: wrap each LLM call and summarization as spans; include metadata such as `schema_version` (derived from README commit hash) and `prompt_version`.
- Scrub secrets and obvious PII before logging.

## Modularity and Extensibility
- Define narrow interfaces:
  - `expand_instructions(question: str) -> str`
  - `generate_cypher(instructions_text: str) -> str`
  - `validate_cypher(cypher: str) -> str`
  - `execute_read(cypher: str) -> List[Dict]`
  - `summarize(question: str, rows: List[Dict]) -> str`
- Implement Gemini-based adapters now; later, replace the expansion/generation pair with LangChain’s `GraphCypherQAChain` while keeping downstream components intact.

## Defaults and Assumptions
- Disease filters only when named; otherwise treat queries as tumor-agnostic.
- Default `LIMIT 100`, maximum `LIMIT 200`, Neo4j timeout 15 seconds.
- No procedures allowed in MVP; revisit once validator hardening is complete.

## Lightweight Testing Strategy
- **Unit tests**: ensure validator blocks write clauses, enforces limits, and flags unknown schema elements; confirm instruction output stays concise.
- **Integration tests** (using seeded CSV graph):
  - KRAS G12C vs. anti-EGFR in colorectal cancer.
  - BRAF V600E sensitivity in melanoma.
  - Negative / no-result scenario.

## Suggested Implementation Order
1. Define module skeletons and interface signatures (no framework coupling).
2. Implement instruction expansion and Cypher generation prompts.
3. Build the safety validator (regex allowlist + schema checks + limit injection).
4. Wire the Neo4j read-only executor with timeout and limit guard.
5. Implement plain-text summarizer leveraging question + rows.
6. Add JSONL logging and LangSmith spans around each LLM call.
7. Write basic unit/integration tests and a simple CLI entrypoint for manual runs.

