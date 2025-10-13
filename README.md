# OncoGraph Agent

A grounded Q&A service over a compact cancer knowledge graph.  
The MVP uses simple, citation-backed CSV data so you can get an end‑to‑end system running quickly and deterministically.

---

## Goal

Answer questions like:

> “Do KRAS mutations affect response to anti‑EGFR therapy in colorectal cancer?”

with:
- A concise, grounded answer  
- A mini‑graph of the relevant entities and relationships  
- PubMed citations  

---

## MVP Architecture

- **Data layer:**
- **Seed data:** small CSVs in `data/manual/`
- **Q&A layer:** user question → LLM → Cypher → Neo4j → citations → response
- **Traces:** every query and response saved for later fine‑tuning  

---

## Getting Started

### 1. Create a virtual environment and install dependencies

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file (or export variables) with:

```
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash      # optional override
GEMINI_TEMPERATURE=0.1             # optional override
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### 3. Seed Neo4j

Run `python -m src.graph.builder` once to ingest the CSV data into Neo4j.

---

## Running the CLI

Use the provided launcher so `src/` is on the Python path:

```powershell
python run.py "Do KRAS mutations affect anti-EGFR therapy in colorectal cancer?"
```

### CLI flags

- `--trace` – stream every pipeline step to stdout (question, instructions, Cypher drafts, row preview, summary text).
- `--debug` – print full stack traces on errors and include them in the JSONL logs.
- `--no-log` – disable JSONL trace writes.

Examples:

```powershell
python run.py --trace --debug "Show therapies targeting BRAF"
python run.py --no-log "Do KRAS mutations affect anti-EGFR therapy in colorectal cancer?"
```

Successful runs echo the final Cypher, result rows (JSON), and the summarised answer. Failures report `Error in step '<name>': …`; add `--debug` for stack traces.

---

## Logging & Debugging

- All runs append structured traces to `logs/traces/YYYYMMDD.jsonl`.
- Each pipeline step records inputs/outputs, including a preview of the first three result rows.
- Error entries capture `error_step`, the error message, and—when `--debug` is supplied—the traceback.
- `--trace` mirrors trace events to stdout for live debugging.

Example trace entry:

```json
{"timestamp": "2025-10-10T17:55:00Z", "step": "generate_cypher", "cypher_draft": "MATCH ..."}
```

---

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
- Schema checks: labels/relationships/properties verified against the MVP schema.
- Normalization: validator rewrites `r.disease_name = 'X'` to `toLower(r.disease_name) = toLower('X')`.
- Neo4j execution: per‑query timeout and fetch size, list normalization for `pmids`/`tags`.

---

## Testing

Run the entire suite:

```powershell
venv\Scripts\python.exe -m pytest
```

Notable coverage:

- `tests/test_validator.py` – clause allowlist, limit enforcement, schema allowlisting.
- `tests/test_executor.py` – Neo4j executor configuration and list normalization.
- `tests/test_gemini.py` – Gemini instruction, Cypher, and summary adapters via stubs.
- `tests/test_pipeline_integration.py` – end-to-end orchestration with deterministic responses.
- `tests/test_cli.py` – CLI output with stubbed engine.

---

## Graph Schema (MVP)

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

### Why No “Statement” Nodes (Yet)

- MVP stores `effect`, `disease`, and `pmids` directly on edges → simplest for LLMs.  
- Reified evidence (Statement + Publication) is planned for later, migration is easy.

---

## CSV‑Driven Seed Data

All CSVs live in `data/manual/` under:

*   **`nodes/genes.csv`**: Defines `Gene` entities.
*   **`nodes/variants.csv`**: Defines `Variant` entities.
*   **`nodes/therapies.csv`**: Defines `Therapy` entities.
*   **`nodes/diseases.csv`**: Defines `Disease` entities.
*   **`relationships/variant_of.csv`**: Creates `VARIANT_OF` relationships.
*   **`relationships/targets.csv`**: Creates `TARGETS` relationships.
*   **`relationships/affects_response.csv`**: Creates the core `AFFECTS_RESPONSE_TO` predictive relationships.

---

## Example User Queries

This system is designed to answer a range of questions by translating them into Cypher queries against the knowledge graph. The MVP should be able to handle queries like the following:

### Complex Queries (Multi-hop)
*   “Do KRAS G12C mutations affect response to Sotorasib in Lung Cancer?”
*   “Show me biomarkers that predict resistance to anti-EGFR therapies in colorectal cancer.”

### Direct Relationship Queries
*   “What gene does Vemurafenib target?”
*   “What are the known variants of the KRAS gene?”
*   “What drugs target BRAF?”

### Node Property Queries
*   “What are the brand names for Cetuximab?”
*   “Give me information about the BRAF V600E variant.”

### Evidence and Citation Queries
*   “What is the evidence that KRAS mutations cause resistance to Cetuximab?”
*   “Find me the PubMed citations related to Sotorasib and KRAS G12C.”

---

## Future Extensions

| Future Add‑on | Purpose |
|----------------|----------|
| Publication nodes & Statement reification | Track per‑paper evidence |
| ClinicalTrial nodes | Link biomarkers, therapies, diseases |
| Drug synonyms & identifiers | From ChEMBL/DrugCentral |
| Disease IDs/synonyms | From Disease Ontology (DOID) |
| Pathway edges | From Reactome |
| Automated ingestion | Pull CIViC data to auto‑extend CSVs |

---

## Licensing & Data Provenance

- All seed data is manually curated by you for testing.  
- When adding external open data (CIViC, HGNC, DOID, ChEMBL, Reactome), keep
  provenance notes and source dates.  
- All mentioned sources are free/open; attribute appropriately when included.

---

**Design philosophy:** *Implement first, perfect later.*  
Get a reliable, small system working end‑to‑end before adding automation or scale.

---

## FastAPI Demo API (Render)

Deploy the pipeline as a web service. Key steps:

1. Ensure `.env` (or Render env) includes:
   - `GOOGLE_API_KEY`
   - `GEMINI_MODEL` / `GEMINI_TEMPERATURE` (optional overrides)
   - `NEO4J_URI` (Aura use `neo4j+s://...`)
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `CORS_ORIGINS=https://<your-vercel-app>.vercel.app`
2. Install deps: `pip install -r requirements.txt`
3. Start locally: `uvicorn api.main:app --reload`
4. Render configuration:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`

Routes:

- `GET /healthz` – health check.
- `POST /query` – body `{ "question": "..." }` → returns `{ answer, cypher, rows }`.

---

## Neo4j Aura Seeding

Use the existing CSVs to populate Aura Free:

```powershell
set NEO4J_URI=neo4j+s://<your-instance>.databases.neo4j.io
set NEO4J_USER=neo4j
set NEO4J_PASSWORD=<password>
python -m src.graph.builder
```

Re-run when seed CSVs change.