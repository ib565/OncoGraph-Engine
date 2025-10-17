# Technical Details

This document provides a deeper dive into the technical implementation of the OncoGraph Agent.


## Graph Schema

### Node Labels

*   **`Gene`**: A specific gene, identified by its official symbol.
    *   *Properties*: `symbol` (unique), `hgnc_id`, `synonyms`
*   **`Variant`**: A specific genetic alteration.
    *   *Properties*: `name` (unique), `hgvs_p`, `consequence`, `synonyms`
*   **`Therapy`**: A medical treatment, typically a drug.
    *   *Properties*: `name` (unique), `modality`, `tags`, `chembl_id`, `synonyms`
*   **`Disease`**: A specific disease, typically a type of cancer.
    *   *Properties*: `name` (unique), `doid`, `synonyms`
*   **`Biomarker`**: A helper label applied to `Gene` and `Variant` nodes to simplify queries.

### Relationship Types

*   **(Variant) -[:VARIANT_OF]-> (Gene)**: Links a variant to its parent gene.
*   **(Therapy) -[:TARGETS]-> (Gene)**: Indicates a therapy is designed to affect a gene.
    *   *Properties*: `source`
*   **(Biomarker) -[:AFFECTS_RESPONSE_TO]-> (Therapy)**: The core predictive fact in the graph.
    *   *Properties*: `effect`, `disease_name`, `disease_id` (optional), `pmids`, `source`, `notes` (optional)


### Index & Uniqueness

- Unique: `Gene.symbol`, `Variant.name`, `Therapy.name`, `Disease.name`  
- Consider indexes on `AFFECTS_RESPONSE_TO.effect` and `Disease.name` when data grows.

### Reification of Statements
The current model stores `effect`, `disease`, and `pmids` directly on edges for simplicity, which is easier for LLMs to handle. A future version may move to reified evidence (e.g., Statement and Publication nodes), and the migration path is straightforward.

## CSV-Driven Seed Data

All CSVs live in `data/manual/` under:

*   **`nodes/genes.csv`**: Defines `Gene` entities.
*   **`nodes/variants.csv`**: Defines `Variant` entities.
*   **`nodes/therapies.csv`**: Defines `Therapy` entities.
*   **`nodes/diseases.csv`**: Defines `Disease` entities.
*   **`relationships/variant_of.csv`**: Creates `VARIANT_OF` relationships.
*   **`relationships/targets.csv`**: Creates `TARGETS` relationships.
*   **`relationships/affects_response.csv`**: Creates the core `AFFECTS_RESPONSE_TO` predictive relationships.


## Logging & Debugging

- All runs append structured traces to `logs/traces/YYYYMMDD.jsonl`.
- Each pipeline step records inputs/outputs, including a preview of the first three result rows.
- Error entries capture `error_step`, the error message, and—when `--debug` is supplied—the traceback.
- `--trace` mirrors trace events to stdout for live debugging.
- API server: set environment variable `TRACE_STDOUT=1` if you also want the FastAPI/uvicorn path to stream trace events to stdout.

Example trace entry:

```json
{"timestamp": "2025-10-10T17:55:00Z", "step": "generate_cypher", "cypher_draft": "MATCH ..."}
```

## LLM Prompts & Query Patterns

- Prompts are schema‑grounded and prefer robust patterns:
  - Gene‑or‑Variant biomarker for generic "<gene> mutations":
    - Either match `(b:Gene {symbol:$GENE})` OR `(b:Variant)-[:VARIANT_OF]->(:Gene {symbol:$GENE})` when traversing `AFFECTS_RESPONSE_TO`.
  - Therapy classes via tags OR targets:
    - `any(tag IN t.tags WHERE toLower(tag) CONTAINS toLower($THERAPY_CLASS))`
      OR `(t)-[:TARGETS]->(:Gene {symbol:$TARGET_GENE})`.
  - Disease comparisons are treated as case‑insensitive (the validator normalizes simple equality).

## Deterministic Guards

- Validation allowlist: blocks write clauses; enforces `LIMIT` with max cap.
- Schema checks: labels/relationships/properties verified against the graph schema.
- Normalization: validator rewrites `r.disease_name = 'X'` to `toLower(r.disease_name) = toLower('X')`.
- Neo4j execution: per‑query timeout and fetch size, list normalization for `pmids`/`tags`.

## Testing Coverage

The test suite provides coverage for key components of the pipeline:

- `tests/test_validator.py` – clause allowlist, limit enforcement, schema allowlisting.
- `tests/test_executor.py` – Neo4j executor configuration and list normalization.
- `tests/test_gemini.py` – Gemini instruction, Cypher, and summary adapters via stubs.
- `tests/test_pipeline_integration.py` – end-to-end orchestration with deterministic responses.
- `tests/test_cli.py` – CLI output with stubbed engine.

## Future Extensions

| Future Add‑on | Purpose |
|----------------|----------|
| Publication nodes & Statement reification | Track per‑paper evidence |
| ClinicalTrial nodes | Link biomarkers, therapies, diseases |
| Drug synonyms & identifiers | From ChEMBL/DrugCentral |
| Disease IDs/synonyms | From Disease Ontology (DOID) |
| Pathway edges | From Reactome |
| Automated ingestion | Pull CIViC data to auto‑extend CSVs |


## Licensing & Data Provenance

- All seed data is manually curated for testing.  
- When adding external open data (CIViC, HGNC, DOID, ChEMBL, Reactome), keep
  provenance notes and source dates.  
- All mentioned sources are free/open; attribute appropriately when included.
