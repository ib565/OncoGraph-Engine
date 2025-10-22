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
  - *Properties*: `source`, `moa`, `action_type`, `ref_sources`, `ref_ids`, `ref_urls`
- **`(Biomarker)-[:AFFECTS_RESPONSE_TO]->(Therapy)`**: The core predictive relationship in the graph.
  - *Properties*: `effect` ('Sensitivity', 'Resistance', etc.), `disease_name`, `pmids`, `source`

### Schema Design Notes

- **Indexes**: Unique constraints are enforced on `Gene.symbol`, `Variant.name`, `Therapy.name`, and `Disease.name`.
- **Simplicity**: For simplicity, evidence details like `effect` and `disease_name` are stored directly on relationships. This is easier for LLMs to query. A future version could move to a more normalized model with dedicated `Evidence` nodes.

## Data Pipeline

The data pipeline transforms raw data from external APIs into the structured graph described above.

1.  **Data Extraction**: The `src/pipeline/civic_ingest.py` script fetches evidence data from the CIViC GraphQL API and enriches it with therapy information (ChEMBL IDs, synonyms, mechanisms of action) from the OpenTargets GraphQL API.
2.  **CSV Generation**: The script outputs a set of clean CSV files in the `data/` directory, corresponding to the nodes and relationships in our schema (e.g., `nodes/genes.csv`, `relationships/affects_response.csv`).
3.  **Graph Ingestion**: The `src.graph.builder` module reads these CSV files and uses them to populate the Neo4j database, creating the nodes and relationships.

This CSV-based approach decouples data extraction from graph ingestion, making the process modular and easy to debug.

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

Prompts are engineered to be schema-aware and produce robust queries. Key patterns include:
-   **Gene vs. Variant Biomarkers**: For a generic question about "KRAS mutations", the LLM generates a query that can match either a `Gene` node or a `Variant` node as the biomarker.
-   **Therapy Classes**: Queries can find therapies by matching tags (e.g., "anti-EGFR therapy") or by finding drugs that target a specific gene.
-   **Case-Insensitive Matching**: The validator automatically normalizes `WHERE` clauses on properties like `disease_name` to be case-insensitive, improving robustness.

### Query Validation & Safety

Before execution, every LLM-generated query passes through a strict validation layer:
-   **Allowlist**: Only read-only clauses (`MATCH`, `WHERE`, `RETURN`) are permitted. All write clauses (`CREATE`, `MERGE`, `DELETE`) are blocked.
-   **Schema Enforcement**: The validator ensures all node labels, relationship types, and properties in the query exist in the graph schema.
-   **Result Limiting**: A `LIMIT` clause is enforced on all queries to prevent excessive data retrieval.

## System Internals

### Logging & Debugging

Structured logs are written to `logs/traces/YYYYMMDD.jsonl` for every run. Each pipeline step records its inputs and outputs.
-   Use the `--trace` flag with the CLI to stream these logs to the console for live debugging.
-   Use the `--debug` flag to capture full stack traces on errors.
-   For the API server, set the environment variable `TRACE_STDOUT=1` to stream traces to the console.

In production/deployment, logs are stored to a Supabase postgres table.


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

