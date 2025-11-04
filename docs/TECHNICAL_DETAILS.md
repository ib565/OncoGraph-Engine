# Technical Details

This document provides implementation details for developers who want to understand or extend OncoGraph's internals. For usage instructions, see the main [README](README.md).

**Core Technical Achievements:**
- **Security-first query engine**: Multi-layer validation (read-only enforcement, parameter blocking, schema allowlisting) prevents injection attacks while enabling flexible natural language queries
- **Two-stage LLM prompting**: Instruction expansion → schema-aware Cypher generation achieves reliable query accuracy
- **High-performance ETL**: Batch operations with Cypher UNWIND deliver 10–100x speedup; parallel processing with graceful error recovery
- **Real-time streaming**: Server-Sent Events (SSE) with background threading and pluggable trace sinks for progressive results
- **Statistical rigor**: Pathway enrichment with hypergeometric testing, FDR correction, and AI-generated biological interpretation
- **Production practices**: Protocol-based architecture with dependency injection, comprehensive testing, TTL caching, retry logic, and structured logging

## Graph Schema

**Node Types:** `Gene`, `Variant`, `Therapy`, `Disease` (with `Biomarker` helper label for unified queries)
**Relationships:** `VARIANT_OF`, `TARGETS`, `AFFECTS_RESPONSE_TO`

**Design Decisions:**
- Unique constraints on primary identifiers (`Gene.symbol`, `Variant.name`, `Therapy.name`, `Disease.name`)
- Evidence metadata stored on relationships for simplicity (tradeoff: denormalization for query performance)
- PMID arrays and structured properties enable citation tracking and filtering

## Data Pipeline

**Architecture:** Decoupled ETL with CSV intermediaries enables independent versioning (timestamped directories), reprocessing without API re-fetching, human-readable debugging, and modular testing.

**Pipeline Stages:**
1. **Extraction** (`civic_ingest.py`): CIViC GraphQL API for evidence; OpenTargets API for therapy enrichment (ChEMBL IDs, mechanisms, targets). Handles pagination, rate limiting, and error recovery.
2. **CSV Generation**: Normalized Neo4j import format with automatic biomarker classification (Gene vs. Variant) and HGVS parsing.
3. **Graph Ingestion** (`graph.builder`): Batch Cypher UNWIND operations (configurable batch size, default 500) with parallel relationship creation.

**Key Features:**
- **Tag derivation**: TARGETS relationships → anti-EGFR tags; suffix heuristics (-mab → Antibody, -tinib → TKI) enable class-based queries
- **Performance optimization**: 10–100x speedup via bulk operations over individual MERGEs; progress logging with timing for observability
- **Graceful error handling**: Continues after individual batch failures; fails gracefully on fatal errors
- **Environment flexibility**: `DATA_DIR` override for switching between seed data and fresh datasets

## Query Engine

**Architecture:** Protocol-based pipeline with dependency injection enables testing and hot-swappable components:
`Expander → Generator → Validator → Executor → Summarizer`

### LLM Prompting Strategy

**Two-stage prompting:**
1. **Instruction expansion**: Natural language → 3–6 schema-aware bullets via instruction-tuned LLM
2. **Cypher generation**: Structured instructions → executable queries with canonical patterns

**Advanced techniques:**
- Schema-aware generation with built-in examples (AFFECTS, TARGETS patterns)
- PMID aggregation: collapse evidence rows to gene–therapy–disease tuples
- Variant matching fallbacks: exact name → contains → hgvs_p → synonyms (with bidirectional fusion support)
- Array safety: `coalesce(..., [])` wrapping; case-insensitive effect filters
- Class-based queries: minimal disease token anchoring; therapy classes via tags or TARGETS

### Security (Defense-in-Depth)

Multi-layer validation prevents injection attacks while enabling flexible queries:
- **Read-only allowlist**: Word-boundary regex blocks CREATE/MERGE/DELETE; allows only MATCH/WHERE/RETURN
- **Parameter blocking**: Rejects `$variables`; requires inline literals to prevent injection
- **Schema enforcement**: Validates labels, relationships, and properties against known allowlist
- **Resource limiting**: Auto-enforces bounded LIMIT (default 100, max 200)
- **Query rewriting**: Automatic case-insensitive disease filter conversion

## Hypothesis Analyzer

Integrates statistical pathway enrichment with AI interpretation for comprehensive gene function analysis.

**Pipeline:**
1. **Gene Normalization**: MyGene API with alias resolution and mutation tolerance
2. **Enrichment Analysis**: GSEAPy against curated databases (GO_Biological_Process_2023, KEGG_2021_Human, Reactome_2022); hypergeometric testing with FDR correction
3. **AI Interpretation**: Gemini-generated biological summaries explaining pathway significance and emergent patterns
4. **Visualization**: Interactive Plotly dot plots (−log₁₀(p-value), odds ratios, gene overlap counts)

**Error Handling**: Invalid symbols excluded with warnings; graceful database fallbacks; comprehensive error messages

## API Architecture

**Endpoints:**
- **Query**: `/query` (sync), `/query/stream` (SSE), `/query/feedback`
- **Enrichment**: `/graph-gene-sets`, `/analyze/genes` (sync), `/analyze/genes/stream` (SSE)

**Design:**
- Protocol-based dependency injection for testing and modularity
- SSE via background threads with `QueueTraceSink` for progressive results
- Comprehensive error handling with context preservation in traces

## System Internals

### Caching & Performance
- **TTL cache**: Thread-safe in-memory cache (default 30min) with deep-copy isolation for LLM and enrichment calls
- **Deterministic hashing**: `stable_hash()` for consistent cache keys across restarts
- **Batch operations**: Parallel processing where dependencies permit; optimized transaction sizes

### Logging & Observability
- **Structured traces**: JSONL logs (`logs/traces/YYYYMMDD.jsonl`) with run IDs, timestamps, and error chains
- **Pluggable sinks**: JSONL, Stdout, Queue (SSE), Postgres, Composite, Filtered
- **Non-fatal design**: Tracing failures don't crash application; graceful degradation
- **Configuration**: CLI flags (`--trace`, `--debug`) or environment variables

### Error Handling & Reliability
- **LLM retry logic**: Exponential backoff (3 attempts) with detailed error context capture
- **Pipeline error wrapping**: Custom `PipelineError` preserves exception chains with step context, input parameters, and timing
- **Graceful degradation**: Fallbacks for rate limits, malformed responses, and transient failures

### Type Safety & Design Patterns
- **Protocol-based architecture**: Components implement protocols for dependency injection and testing without inheritance
- **Pydantic models**: Request/response validation with field constraints; frozen dataclass configs
- **Structured outputs**: JSON parsing with validation; automatic fallback handling

## Testing

Comprehensive `pytest` suite covering:
- **Security**: Validator constraints, parameter blocking, schema enforcement, read-only verification
- **Pipeline integration**: End-to-end query flow, LLM adapters, structured output parsing, retry logic
- **Enrichment**: Gene normalization, statistical calculations, multi-database queries, AI summarization
- **API**: Request validation, error responses, SSE streaming
- **Test architecture**: Fixtures for database isolation, mock objects for external APIs, snapshot testing for LLM outputs

## Local Development Setup

### Prerequisites
- Python 3.10+, Neo4j Desktop/Server, Node.js 16+
- Google Gemini API key ([get one here](https://ai.google.dev/))

### Setup

**1. Environment variables** - Create `.env` in project root:
```bash
GOOGLE_API_KEY="your_gemini_api_key_here"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="your_password"
```

**2. Backend:**
```bash
python -m venv venv
source venv/bin/activate  # or .\venv\Scripts\activate (Windows)
pip install -r requirements.txt && pip install -e .
```

**3. Database:**
```bash
# Start Neo4j, then seed with included data:
python -m src.graph.builder

# Or generate fresh data from CIViC/OpenTargets:
python -m src.pipeline.civic_ingest --out-dir data/civic/latest --enrich-tags
DATA_DIR="data/civic/latest" python -m src.graph.builder
```

**4. Run:**
```bash
# Backend (terminal 1)
uvicorn api.main:app --reload

# Frontend (terminal 2)
cd web && npm install
NEXT_PUBLIC_API_URL="http://localhost:8000" npm run dev
```

Visit `http://localhost:3000` for UI, `http://localhost:8000/docs` for API docs.

**5. Test:**
```bash
python -m pytest
```

## Future Extensions

| Feature                             | Purpose                                                     |
| ----------------------------------- | ----------------------------------------------------------- |
| Fine tuned Cypher generation model | ✅ **Completed** - Two models trained (Qwen3-1.7B and Qwen3-4B) with 72.5% and 91.25% accuracy. See [Fine-Tuning Overview](FINETUNING_OVERVIEW.md) |
| Publication & Statement Nodes       | Track per-paper evidence for finer-grained provenance.      |
| Clinical Trial Nodes                | Link biomarkers, therapies, and diseases to trials.         |
| Enhanced Drug & Disease Ontologies | Integrate synonyms and identifiers from ChEMBL and DOID.    |
| Pathway Data                        | Add `(:Gene)-[:PART_OF_PATHWAY]->(:Pathway)` from Reactome. |
| Automated Ingestion                 | Set up a recurring job to pull the latest data from CIViC.  |
| Advanced Enrichment Analysis        | Support for custom gene sets, additional databases, and comparative analysis. |
| Interactive Pathway Visualization   | Enhanced pathway diagrams with gene expression overlays.    |

