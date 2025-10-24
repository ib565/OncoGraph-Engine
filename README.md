# OncoGraph Engine
**Knowledge‑graph Q&A + pathway enrichment for oncology research.**

---

## Links
- **Live demo:** [https://onco-graph.vercel.app/](https://onco-graph.vercel.app/)
- **90‑sec video:** `<add_url>`

---

## Overview
- Ask natural‑language questions about genes, variants, therapies, diseases, etc. Answers are grounded in a Neo4j knowledge graph with citations.  
- Paste or assemble gene lists and run pathway enrichment (Enrichr/GSEApy). Get a concise AI summary and one‑click follow‑up graph queries.  
- Built to mirror a practical discovery workflow: **data → mechanism → action**.

---

## Key features

### Graph Q&A
- LLM parses question → generates Cypher → executes on Neo4j.  
- Results with PMIDs and sources, plus an interactive subgraph and raw Cypher.

### Hypothesis Analyzer
- Over‑representation analysis (ORA) via Enrichr (Reactome 2022, GO BP 2023, KEGG 2021 Human).  
- Dot plot of enriched terms, AI summary, and suggested next steps that call back into the graph.

### Convenience bridges
- One click: send genes from a Q&A result to the Analyzer.  
- One click: run suggested follow‑up queries from Analyzer results.

### Transparent by design
- Show recognized entities, citations, sources, and the executed Cypher.

---

## Data sources

### CIViC (Clinical Interpretations of Variants in Cancer)
- Used for variant‑level evidence of therapy response (sensitivity/resistance) with PubMed IDs.

### OpenTargets
- Used for therapy → gene TARGETS relationships and mechanism of action tags.

---

## Scope and limitations
- Public, curated data only; not exhaustive.  
- Evidence is stored on relationships (no reified evidence graph in V1).  
- Results are **for research and education**. Do not use for clinical decisions.

---

## Architecture
- **Frontend:** Next.js (React, TypeScript) on Vercel.  
- **API:** FastAPI (Python) on Render.  
- **Graph DB:** Neo4j.  
- **LLM:** Gemini (question expansion, cypher generation, summarization).  
- **Enrichment:** GSEApy with Enrichr.

---

## Schema (V1)

### Nodes
- **Gene** `{symbol, hgnc_id?, synonyms}`
- **Variant** `{name, hgvs_p?, consequence?, synonyms}`
- **Therapy** `{name, modality?, tags?, chembl_id?, synonyms}`
- **Disease** `{name, doid?, synonyms}`

### Relationships
- `(Variant)-[:VARIANT_OF]->(Gene)`
- `(Therapy)-[:TARGETS]->(Gene)`
- `(Variant or Gene)-[AFFECTS_RESPONSE_TO]->(Therapy)`  
  - **Properties:**  
    - `effect (Sensitivity|Resistance)`  
    - `disease_name`, `disease_id?`, `pmids (array)`, `source`, `notes?`

### Notes
- “Biomarker” is used as an extra label on Gene/Variant for convenience.  
- Pathway/Analysis nodes are not added yet.

---

## How to use

### A. Detailed workflow (demo script)

**Title:** *Anti‑EGFR resistance in colorectal cancer → pathway rationale → therapeutic options*

#### 1) Graph Q&A
Query (paste and run):

```text
Which genes predict resistance to cetuximab or panitumumab in colorectal cancer?
```

Expect genes such as KRAS, NRAS, BRAF, EGFR, MAP2K1, ERBB2/3, PIK3CA, PTEN, FBXW7, SMAD4, HRAS, NRG1 with PMIDs.

#### 2) Send genes to Hypothesis Analyzer
Click “Send genes to Analyzer” or paste:

```text
KRAS, NRAS, BRAF, EGFR, MAP2K1, ERBB2, ERBB3, PIK3CA, PTEN, FBXW7, SMAD4, HRAS, NRG1
```

Libraries: Reactome 2022, GO Biological Process 2023, KEGG 2021 Human.  
Read the AI summary; inspect the dot plot (−log10 FDR).

#### 3) Follow‑ups (from suggested buttons or paste in Q&A)
Example:

```text
Which therapies target ERBB2, MAP2K1, or PIK3CA, and what are their mechanisms of action?
```

Optional:

```text
Which KRAS, NRAS, or BRAF variants are known resistance biomarkers for anti‑EGFR therapy in colorectal cancer?
Note: such queries may return a lot of results.
```

**Narrative**
- Pull clinically observed resistance genes (CIViC).  
- Show they converge on ErbB/MAPK signaling (Analyzer).  
- Pivot to actionable levers (ERBB2/MAPK/PI3K targets) and evidence.

---

### B. Brief workflow

**Title:** *HRD → PARP inhibitor rationale (ovarian cancer)*

#### 1) Graph Q&A
```text
Which biomarkers predict sensitivity to PARP inhibitors (olaparib, rucaparib, etc.) in ovarian cancer?
```

#### 2) Hypothesis Analyzer
Paste:

```text
BRCA1, BRCA2, CDK12, ARTN, NBN
```

Enrichment in Homologous Recombination DNA repair, etc.

#### 3) Follow‑up
```text
Which therapies target genes BRCA1 or BRCA2 in ovarian cancer?
```

---

## Example Q&A queries (copy/paste)

### Therapy‑centric
- Which therapies target ERBB2, and what are their mechanisms of action?  
- What therapies target BRAF, and what are their modalities or tags?

### Biomarker‑centric
- Which KRAS variants affect response to panitumumab in colorectal cancer?  
- Provide PubMed IDs supporting that EGFR S492R confers resistance to cetuximab in colorectal cancer.

### Disease‑centric
- List therapies that have variant‑level biomarkers in non‑small cell lung cancer.  
- In colorectal cancer, which variants in ERBB2 or EGFR have biomarker evidence affecting response to any therapy?

---

## Example Analyzer gene lists

### Immune checkpoints and cytotoxicity
```text
PDCD1, CD274, CTLA4, LAG3, TIGIT, PRF1, GZMB
```

### CRC drivers (mechanism mapping)
```text
KRAS, TP53, APC, PIK3CA, SMAD4, BRAF, NRAS
```

### MAPK probe
```text
KRAS, NRAS, BRAF, MAP2K1, MAP2K2, EGFR
```

---

## UI notes

### Q&A tab
- Query box, example queries, answer with citations, interactive subgraph, raw Cypher, copy to clipboard, move to Analyzer.

### Hypothesis Analyzer tab
- Paste genes or pull from preset gene sets.  
- Show used vs missing symbols, results table, dot plot, AI summary, and suggested next steps.

---

## Install and run (local)

### Prerequisites
- Python 3.10+  
- Neo4j Desktop or Server  
- Node.js and npm

---

### 1. Configure Environment

Create a `.env` file in the project root with the following variables:

```bash
GOOGLE_API_KEY="your_gemini_api_key"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="your_password"
```

---

### 2. Setup Backend

Create a virtual environment and install dependencies:

```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies and the local package
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

---

### 3. Seed the Database

You can use the small, included dataset or generate a fresh one from the source APIs.

#### Option A: Use the included seed data (Recommended for quick start)
```bash
python -m src.graph.builder
```

#### Option B: Generate data from CIViC + OpenTargets
```bash
# Generate CSVs under data/civic/latest
python -m src.pipeline.civic_ingest --out-dir data/civic/latest --enrich-tags

# Point the builder to the generated dataset and ingest
$env:DATA_DIR="data/civic/latest"
python -m src.graph.builder
```

---

### 4. Run the Application

**Start the Backend API:**
```bash
uvicorn api.main:app --reload
```

**Run the Web Interface:**
```bash
# Navigate to the web directory
cd web

# Install dependencies
npm install

# Set the API URL and run the development server
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"
npm run dev
```

The UI will be available at [http://localhost:3000](http://localhost:3000).

---

### 5. Run Tests

To run the backend test suite:

```bash
python -m pytest
```

---

## Methods

### Knowledge Graph
- CIViC “Evidence Items” map to `AFFECTS_RESPONSE_TO` with effect, disease_name, pmids, source.  
- OpenTargets provides therapy→gene TARGETS edges and mechanism/meta tags when available.

### Enrichment
- Over‑representation analysis via Enrichr (GSEApy).  
- Libraries: Reactome 2022, GO Biological Process 2023, KEGG 2021 Human.  
- Significance: adjusted p‑value (FDR). Plots show −log10(FDR).

---

## Roadmap
- Persist saved analyses to the graph: `(Analysis)-[:ENRICHED_IN]->(Pathway)` and `(Gene)-[:HIT_IN_ANALYSIS]->(Pathway)`.  
- Clinical Trial Nodes (link biomarkers, therapies, diseases to trials).  
- Reified evidence model (Statement/Publication nodes).  
- Additional public sources (e.g., ChEMBL, COSMIC, OncoKB).

---

## License and attribution
- Data courtesy of CIViC and OpenTargets. Respect their licenses and terms of use.

---

## Disclaimer
Research tool only. **Not intended for diagnosis, treatment, or clinical decision‑making.**  
Always consult primary literature and domain experts.
