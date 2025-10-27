# OncoGraph Engine

**Knowledge-graph Q&A + pathway enrichment for oncology research**

[Try the live demo](https://onco-graph-engine.vercel.app/) | [Watch the 2-min demo](https://www.youtube.com/watch?v=4HtPS-SvBwk)

---

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://onco-graph-engine.vercel.app/)
[![Watch the demo](https://img.shields.io/badge/watch--on-YouTube-red?logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=4HtPS-SvBwk)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## What Problem Does This Solve?

When computational models predict a gene signature affects drug response, 
researchers need to:
1. **Validate** - Is this finding supported by clinical evidence?
2. **Interpret** - What biological mechanism explains this pattern?
3. **Act** - What therapies target this mechanism?

This typically requires hours of manual work across multiple tools.

**OncoGraph integrates the entire workflow into minutes:**
- Query clinical evidence in natural language
- Interpret biological mechanisms via pathway enrichment
- Explore therapeutic options through the knowledge graph
- All with traceable sources and exportable results

**Complements AI discovery platforms:** When models (e.g., Noetik's OCTO) 
predict gene signatures from spatial data, OncoGraph validates them 
against clinical evidence, interprets the mechanism, and identifies 
therapeutic options.

---

## Complete Workflow: KRAS G12D Resistance in Colorectal Cancer

This example demonstrates OncoGraph's end-to-end workflow for 
understanding therapy resistance and finding alternatives.

### Step 1: Identify Resistance Mechanisms
**Query:** "Which genes predict resistance to cetuximab or panitumumab 
in colorectal cancer?"

**Result:** 13 genes including KRAS, NRAS, BRAF, ERBB2, PIK3CA, etc.  
**Evidence:** 88 evidence items across 45 PMIDs

### Step 2: Understand Biological Mechanism
**Action:** Click "Move to Hypothesis Analyzer"  
**Result:** Enrichment in ErbB signaling pathway (p < 1e-19)

**AI Summary:** "These genes converge on receptor tyrosine kinase 
signaling. Dysregulation allows tumor cells to maintain proliferative 
signals despite EGFR blockade."

### Step 3: Find Alternative Therapeutic Targets
**Action:** Click suggested query "Which therapies target ERBB2, 
MAP2K1, or PIK3CA?"

**Result:** 
- ERBB2 inhibitors: trastuzumab, pertuzumab, etc.
- MEK inhibitors: trametinib, cobimetinib
- PI3K inhibitors: alpelisib, copanlisib

**Insight:** Patients with anti-EGFR resistance may benefit from 
combination strategies targeting downstream pathways.

**Time:** ~7 minutes from question to actionable hypothesis  
**Manual equivalent:** 45-60 minutes

---

## Why OncoGraph?

| Task | Manual Approach | OncoGraph |
|------|----------------|-----------|
| Find resistance biomarkers | Search CIViC → read 20+ evidence items | Natural language query → results with PMIDs |
| Understand mechanism | Read papers → search pathway databases | One-click enrichment + AI summary |
| Find alternative targets | Formulate hypothesis → search again | Suggested follow-up queries |
| **Time per iteration** | **30-60 minutes** | **5-7 minutes** |

**The value is integration:** Reduce friction at every step of the discovery loop.

---

## Quick Start

**Try it now (no installation required):**

1. Visit the [live demo](https://onco-graph-engine.vercel.app/)
2. Click any example query, or try: `"Which genes predict resistance to cetuximab in colorectal cancer?"`
3. Click **"Move to Hypothesis Analyzer"** when results appear
4. Review pathway enrichment + AI summary
5. Click suggested follow-up queries to continue exploring

**See the complete workflow example below for detailed walkthrough.**

---

## Key Features

**Natural Language Graph Queries**
- Ask questions in plain English about genes, variants, therapies, diseases
- LLM generates Cypher query → executes on Neo4j knowledge graph
- Results include PMIDs, sources, interactive visualization, and raw Cypher
- One-click export of genes to Hypothesis Analyzer

**Pathway Enrichment Analysis**
- Over-representation analysis via Enrichr (Reactome 2022, GO BP 2023, KEGG 2021)
- Dot plot visualization of enriched pathways
- AI-generated summary explaining biological significance
- Suggested follow-up queries that execute in Graph Q&A tab

**Integrated Workflow**
- Seamless transitions: Query → Enrichment → Follow-up → Repeat
- All sources traceable to PMIDs

**Transparent by Design**
- Display raw Cypher and raw results for validation

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
- **Frontend:** Next.js (React, TypeScript) → Vercel
- **Backend:** FastAPI (Python) → Render
- **Database:** Neo4j (knowledge graph)
- **LLM:** Gemini (query parsing, Cypher generation, summarization)
- **Enrichment:** GSEApy with Enrichr libraries

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
  - **Properties:** `source`, `moa?`, `action_type?`, `ref_sources?`, `ref_ids?`, `ref_urls?`
- `(Variant or Gene)-[AFFECTS_RESPONSE_TO]->(Therapy)`  
  - **Properties:**  
    - `effect (Sensitivity|Resistance)`  
    - `disease_name`, `disease_id?`, `pmids (array)`, `source`, `notes?`

### Notes
- “Biomarker” is used as an extra label on Gene/Variant for convenience.  
- Pathway/Analysis nodes are not added yet.

---

## Scientific Validation

OncoGraph has been validated against established findings:

### KRAS Mutations in Anti-EGFR Therapy

**Query:** "Which KRAS variants predict resistance to cetuximab in colorectal cancer?"

**Results:** Correctly identified 28+ KRAS variants including G12D, G12V, G13D with supporting PMIDs

**Validation:** Cross-referenced with landmark study PMID:17363584 (Di Nicolantonio et al., 2008)

**Clinical relevance:** Directly informs treatment decisions for mCRC patients

### BRAF-Targeted Therapies

**Query:** "What therapies target BRAF mutations?"

**Results:** FDA-approved BRAF inhibitors (dabrafenib, vemurafenib, encorafenib) plus 10 additional agents

**Validation:** Matches current NCCN guidelines for BRAF-mutant cancers

*OncoGraph is a research tool. Validate all results against primary literature before clinical application.*

---

## Example Queries & Gene Lists

### Graph Q&A Examples

**Therapy-centric:**
- Which therapies target ERBB2, and what are their mechanisms of action?
- What therapies target BRAF, and what are their modalities?

**Biomarker-centric:**
- Which KRAS variants affect response to panitumumab in colorectal cancer?
- Provide PMIDs supporting that EGFR S492R confers resistance to cetuximab

**Disease-centric:**
- List therapies with variant-level biomarkers in non-small cell lung cancer
- In colorectal cancer, which ERBB2 or EGFR variants have biomarker evidence?

### Gene Lists for Hypothesis Analyzer

**Anti-EGFR resistance (colorectal cancer):**
```
KRAS, NRAS, BRAF, EGFR, MAP2K1, ERBB2, ERBB3, PIK3CA, PTEN, FBXW7, SMAD4
```

**Immune checkpoints:**
```
PDCD1, CD274, CTLA4, LAG3, TIGIT, PRF1, GZMB
```

**MAPK pathway:**
```
KRAS, NRAS, BRAF, MAP2K1, MAP2K2, EGFR
```

---

## Install and run (local)

### Prerequisites
- Python 3.10+  
- Neo4j Desktop or Server  
- Node.js and npm


### 1. Configure Environment

Create a `.env` file in the project root with the following variables:

```bash
GOOGLE_API_KEY="your_gemini_api_key"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="your_password"
```

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
- Normalize gene symbols using MyGene.info.
- Over‑representation analysis via Enrichr (GSEApy).  
- Libraries: Reactome 2022, GO Biological Process 2023, KEGG 2021 Human.  
- Significance: adjusted p‑value (FDR). Plots show −log10(FDR).

---

## Roadmap
- **Fine tune a model for Cypher generation.**
- Persist saved analyses to the graph: `(Analysis)-[:ENRICHED_IN]->(Pathway)` and `(Gene)-[:HIT_IN_ANALYSIS]->(Pathway)`.  
- Clinical Trial Nodes (link biomarkers, therapies, diseases to trials).  
- Reified evidence model (Statement/Publication nodes).  
- Additional public sources (e.g., ChEMBL, COSMIC, OncoKB).

---

## License & Attribution

**Code:** MIT License  
**Data:** CIViC and OpenTargets (CC0 1.0 Public Domain)

See [LICENSE](LICENSE) file for full details.

---

## Contributing & Feedback

Built as a research tool for the computational oncology community. 
Feedback, suggestions, and contributions are welcome.

Contact: [ish.bhartiya@gmail.com](ish.bhartiya@gmail.com)

---

## Disclaimer
Research tool only. **Not intended for diagnosis, treatment, or clinical decision‑making.**  
Always consult primary literature and domain experts.
