# Technical Details

This document provides a deeper dive into the technical implementation of the OncoGraph Agent, covering the graph schema, data pipeline, and query engine.

## Graph Schema

The knowledge graph consists of four primary node types and three relationship types.

### Node Labels

- **`Gene`**: A gene, identified by its official symbol.
  - *Properties*: `symbol` (unique), `hgnc_id`, `synonyms`
- **`Variant`**: A specific genetic alteration.
  - *Properties*: `name` (unique), `hgvs_p`, `consequence`, `synonyms`
- **`Therapy`**: A medical treatment, typically a drug.
  - *Properties*: `name` (unique), `modality`, `tags`, `chembl_id`, `synonyms`
- **`Disease`**: A specific disease, typically a type of cancer.
  - *Properties*: `name` (unique), `doid`, `synonyms`
- **`Biomarker`**: A helper label applied to `Gene` and `Variant` nodes to simplify queries about biomarkers.

### Relationship Types

- **`(Variant)-[:VARIANT_OF]->(Gene)`**: Links a variant to its parent gene.
- **`(Therapy)-[:TARGETS]->(Gene)`**: Indicates a therapy is designed to affect a gene.
  - *Properties*: `source`, `moa?`, `action_type?`, `ref_sources?`, `ref_ids?`, `ref_urls?`
- **`(Biomarker)-[:AFFECTS_RESPONSE_TO]->(Therapy)`**: The core predictive relationship in the graph.
  - *Properties*: `effect` ('Sensitivity', 'Resistance', etc.), `disease_name`, `disease_id?`, `pmids` (array), `source`, `notes?`

### Schema Design Notes

- **Indexes**: Unique constraints are enforced on `Gene.symbol`, `Variant.name`, `Therapy.name`, and `Disease.name`.
- **Simplicity**: For simplicity, evidence details like `effect` and `disease_name` are stored directly on relationships. This is easier for LLMs to query. A future version could move to a more normalized model with dedicated `Evidence` nodes.

## Data Pipeline

The data pipeline transforms raw data from external APIs into the structured graph described above.

1.  **Data Extraction**: The `src/pipeline/civic_ingest.py` script fetches evidence data from the CIViC GraphQL API and enriches it with therapy information (ChEMBL IDs, synonyms, mechanisms of action) from the OpenTargets GraphQL API.
2.  **CSV Generation**: The script outputs a set of clean CSV files in the `data/` directory, corresponding to the nodes and relationships in our schema (e.g., `nodes/genes.csv`, `relationships/affects_response.csv`).
3.  **Graph Ingestion**: The `src.graph.builder` module reads these CSV files and uses them to populate the Neo4j database, creating the nodes and relationships.

This CSV-based approach decouples data extraction from graph ingestion, making the process modular and easy to debug.

### CIViC Ingestion Features

**Hybrid TARGETS Population**
- Curated seed pairs for well-established drug-target relationships (e.g., Imatinib → ABL1, Dabrafenib → BRAF)
- Heuristic-based inference: if majority of sensitivity evidence involves gene X, infer therapy targets X
- Denylist to prevent false inferences (e.g., Cetuximab does NOT target KRAS, it targets EGFR)
- OpenTargets enrichment for mechanism of action tags and references

**Tag Enrichment**
- Automatic inference from TARGETS relationships: if therapy targets EGFR, add "anti-EGFR" tag
- Suffix heuristics: "-mab" → "antibody", "-tinib" → "TKI inhibitor"
- Enables class-based queries (e.g., "anti-EGFR therapies")

**Biomarker Classification**
- Automatically determines if evidence involves a specific `Variant` or a generic `Gene` biomarker
- Sets `biomarker_type` column ("Gene" or "Variant") for graph builder to create correct node types
- Parses HGVS notation when available for standardized variant representation

**Batch Processing**
- Configurable batch size for Neo4j ingestion (default 500 records)
- Uses UNWIND for efficient bulk writes
- Progress logging with record counts and timing
- Error recovery: continues after individual batch failures where possible

### Graph Builder Features

**Constraint Creation**
- Enforces unique constraints on `Gene.symbol`, `Variant.name`, `Therapy.name`, `Disease.name`
- Uses `CREATE CONSTRAINT IF NOT EXISTS` to avoid errors on repeated runs

**CSV Cleaning**
- Handles empty cells, NaN values, extra whitespace
- Preserves array fields (synonyms, pmids, tags) as semicolon-delimited strings
- Automatic type inference for integer/float fields

**Relationship Creation**
- Special handling for `AFFECTS_RESPONSE_TO`: creates relationship based on `biomarker_type` (Gene or Variant)
- Bulk UNWIND operations for performance
- Supports parallel ingestion of multiple relationship types

**Environment Override**
- Can specify custom data directory via `DATA_DIR` environment variable
- Enables easy switching between seed data and freshly generated datasets
- Defaults to `data/manual` for quick start

## Query Engine

The query engine is responsible for translating a user's question into a safe, executable Cypher query and then summarizing the results.

## Hypothesis Analyzer

The Hypothesis Analyzer provides functional enrichment analysis for gene lists, complementing the knowledge graph queries with pathway and biological process analysis.

### Gene Enrichment Pipeline

1. **Gene Normalization:** Input gene symbols are normalized using MyGene to resolve aliases and validate against official gene symbols.
2. **Enrichment Analysis:** Valid genes are analyzed using GSEAPy's enrichr function against standard databases:
   - GO_Biological_Process_2023
   - KEGG_2021_Human  
   - Reactome_2022
3. **AI Interpretation:** Gemini generates biological summaries explaining the top enriched pathways and their significance.
4. **Visualization:** Results are formatted for interactive Plotly dot plots showing statistical significance and gene counts.

### API Endpoints

- **`POST /analyze/genes`**: Accepts comma or newline-separated gene lists and returns structured enrichment results with AI summaries and visualization data.

### Error Handling

- Invalid gene symbols are identified and excluded from analysis with user warnings
- Graceful fallback when enrichment databases are unavailable
- Comprehensive error messages for debugging and user feedback

### LLM Prompting & Query Patterns

**Two-Stage Architecture**
The pipeline uses a sophisticated two-stage prompting system:
1. **Instruction Expansion**: Converts natural language question into 3-6 bullet points referencing schema elements
2. **Cypher Generation**: Transforms bullet points into executable Cypher query

This separation of concerns improves accuracy by giving the model schema context before query construction.

**Prompt Engineering Techniques**
- **Schema Snippets**: Condensed schema embedded in every prompt with canonical examples
- **Canonical Patterns**: Reference implementations for common query types (AFFECTS, TARGETS, gene-only)
- **PMID Aggregation Logic**: Explicit instructions for collapsing gene-level evidence and aggregating PubMed IDs
- **Fallback Strategies**: Multiple matching approaches for variants (equality, CONTAINS, hgvs_p, synonyms)
- **Array Safety**: Always wrap array properties with `coalesce(..., [])` to handle nulls
- **Effect Filtering**: Case-insensitive comparison via `toLower(rel.effect)`

**Key Query Patterns**
- **Gene vs. Variant Biomarkers**: For a generic question about "KRAS mutations", the LLM generates a query that can match either a `Gene` node or a `Variant` node as the biomarker.
- **Therapy Classes**: Queries can find therapies by matching tags (e.g., "anti-EGFR therapy") or by finding drugs that target a specific gene.
- **Disease Umbrella Terms**: Minimal anchor filtering (e.g., "lung" in "lung cancer") to maximize recall without specificity loss
- **Variant Fusion Handling**: Bidirectional matching for gene fusions (EML4::ALK and ALK::EML4)
- **Token vs. Full Name**: Different handling for bare tokens (G12C) vs. full variant names (KRAS G12C)

### Query Validation & Safety

Before execution, every LLM-generated query passes through a strict validation layer:
-   **Allowlist**: Only read-only clauses (`MATCH`, `WHERE`, `RETURN`) are permitted. All write clauses (`CREATE`, `MERGE`, `DELETE`) are blocked.
-   **Schema Enforcement**: The validator ensures all node labels, relationship types, and properties in the query exist in the graph schema.
-   **Result Limiting**: A `LIMIT` clause is enforced on all queries to prevent excessive data retrieval.

## System Internals

### Caching System

The pipeline implements a sophisticated multi-level caching system to optimize performance and reduce API costs:

**TTLCache Implementation**
- Thread-safe in-memory cache using `threading.RLock()` for concurrent access
- Configurable TTL (default 1800 seconds = 30 minutes) per cache type
- Deep copying to prevent mutation of cached values
- Automatic expiration and cleanup on access
- TTL can be disabled (set to 0) for development

**Cache Categories**
- **LLM Cache**: Caches instruction expansion, Cypher generation, and summarization results to avoid redundant Gemini API calls. Uses `stable_hash()` on inputs to generate deterministic cache keys.
- **Enrichment Cache**: Caches gene normalization results and enrichment analysis to speed up repeated gene set queries.

**Cache Keys**
- Use stable hashing via `stable_hash()` which sorts dict keys and uses consistent JSON formatting
- Example: `expand_instructions:{sha256_hash(question)}`
- Preserves consistency across restarts and cache invalidation

### Logging & Debugging

Structured logs are written to `logs/traces/YYYYMMDD.jsonl` for every run. Each pipeline step records its inputs and outputs.
-   Use the `--trace` flag with the CLI to stream these logs to the console for live debugging.
-   Use the `--debug` flag to capture full stack traces on errors.
-   For the API server, set the environment variable `TRACE_STDOUT=1` to stream traces to the console.

In production/deployment, logs are stored to a Supabase postgres table.

**Tracing Architecture**
The pipeline uses a pluggable tracing system with multiple sink types:
- `JsonlTraceSink`: Appends to daily JSONL files
- `StdoutTraceSink`: Prints to console for live debugging
- `QueueTraceSink`: Pushes events to queues for SSE streaming
- `PostgresTraceSink`: Persists to Postgres JSONB columns
- `CompositeTraceSink`: Forwards to multiple sinks simultaneously
- `ContextTraceSink`: Injects fixed context (e.g., run_id) into every event
- `FilteredTraceSink`: Selects only specific steps for a sink

All trace sinks are non-fatal: tracing failures never crash the pipeline.

### Query Safety & Security

**Parameter Blocking**
- All parameterized queries (e.g., `$GENE`) are explicitly blocked
- Requires literal inlined values to prevent injection attacks
- Validator pattern-matches for any `$variable` syntax and rejects with clear error

**Read-Only Enforcement**
- Allowlist of allowed keywords: `MATCH`, `WHERE`, `RETURN`, `WITH`, `OPTIONAL`, `LIMIT`, `ORDER BY`, `SKIP`
- Blocklist of forbidden keywords: `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `CALL`, `LOAD`, `DROP`, `DETACH`
- Pattern matching uses regex word boundaries to avoid false positives

**Schema Enforcement**
- Validates all node labels against `ALLOWED_LABELS` set
- Validates all relationship types against `ALLOWED_RELATIONSHIPS` set  
- Enforces known property names via `ALLOWED_PROPERTIES` for extra safety
- Strips string literals before scanning to avoid false positives on user data

**Result Limiting**
- Automatically enforces `LIMIT` clause on all queries
- Default limit: 100 rows (configurable)
- Maximum limit: 200 rows (configurable)
- Replaces missing or excessive LIMIT values

**Case-Insensitive Matching**
- Automatically rewrites disease name filters to case-insensitive form
- Example: `d.disease_name = 'Lung Cancer'` → `toLower(d.disease_name) = toLower('Lung Cancer')`
- Improves query robustness for user input variations

### Retry Logic & Error Handling

**Gemini API Retries**
- Exponential backoff: 1s, 2s, 4s delays between 3 attempts
- Comprehensive error extraction: captures `details`, `code`, `status_code`, `reason`
- Detailed logging of each attempt with full context
- Preserves original exception chain for debugging
- Non-fatal error handling: returns graceful fallbacks where possible

**Pipeline Error Tracking**
- Custom `PipelineError` class with `step` field to identify failure point
- All pipeline steps wrapped in try-catch with specific error messages
- Error context includes: step name, input data, timing information
- Maintains exception chain for stack trace preservation

### Type Safety & Architecture

**Protocol-Based Design**
- Uses Python's `Protocol` (structural typing) for dependency injection
- Components: `InstructionExpander`, `CypherGenerator`, `CypherValidator`, `CypherExecutor`, `Summarizer`
- Makes testing easier: can inject mock implementations
- No tight coupling to specific classes

**Pydantic Models**
- Request/Response models for API layer: `QueryRequest`, `QueryResponse`, `GeneListRequest`, `EnrichmentResponse`
- Validation via Pydantic `Field` constraints (min_length, etc.)
- Structured output for enrichment summaries: `EnrichmentSummaryResponse` with Gemini's native JSON mode
- Automatic serialization/deserialization

**Dataclasses for Configuration**
- `PipelineConfig`: Immutable configuration for pipeline behavior
- `GeminiConfig`: Model, temperature, API key settings
- `QueryEngineResult`: Structured return type with answer, cypher, rows
- All use `@dataclass(frozen=True)` for immutability

**Structured Output with Gemini**
- Uses Gemini's native `response_mime_type="application/json"`
- Provides JSON schema via `response_schema` parameter
- Automatic parsing and validation of structured responses
- Fallback error handling if JSON parsing fails


### Testing Coverage

The `pytest` suite covers key components of the backend pipeline, including the query validator, Neo4j executor, LLM adapters, and end-to-end integration tests. The Hypothesis Analyzer includes comprehensive tests for:

- Gene normalization and validation logic
- Enrichment analysis pipeline
- API endpoint functionality and error handling
- AI summarization of enrichment results
- Plot data generation for visualizations

## Future Extensions

| Feature                             | Purpose                                                     |
| ----------------------------------- | ----------------------------------------------------------- |
| Publication & Statement Nodes       | Track per-paper evidence for finer-grained provenance.      |
| Clinical Trial Nodes                | Link biomarkers, therapies, and diseases to trials.         |
| Enhanced Drug & Disease Ontologies | Integrate synonyms and identifiers from ChEMBL and DOID.    |
| Pathway Data                        | Add `(:Gene)-[:PART_OF_PATHWAY]->(:Pathway)` from Reactome. |
| Automated Ingestion                 | Set up a recurring job to pull the latest data from CIViC.  |
| Advanced Enrichment Analysis        | Support for custom gene sets, additional databases, and comparative analysis. |
| Interactive Pathway Visualization   | Enhanced pathway diagrams with gene expression overlays.    |

