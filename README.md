# OncoGraph

**Knowledge-graph Q&A + pathway enrichment for oncology research w/ fine-tuned models for text-to-Cypher**

[Try the live deployment](https://oncograph.vercel.app/) | [Watch the 2-min demo](https://www.youtube.com/watch?v=1XboGF-kAmI) | [Fine-Tuned Models](docs/FINETUNING_OVERVIEW.md) | [📊 Model Evaluation](https://ib565.github.io/OncoGraph/model_evaluation_report.html)

**For developers:** 
- [Technical Details](docs/TECHNICAL_DETAILS.md) — Architecture, security, testing, etc
- [Fine-Tuning (Text-to-Cypher)](docs/FINETUNING_DETAILS.md) — Overview, technical details, etc. *Note: Fine tuned models are not deployed, looking for cheap inference options.*

---

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://oncograph.vercel.app/)
[![Watch the demo](https://img.shields.io/badge/watch--on-YouTube-red?logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=1XboGF-kAmI)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## What It Does

Ask questions like *"Which genes predict resistance to cetuximab in colorectal cancer?"* and get:
- **Clinical evidence** with PMIDs from curated databases (CIViC, OpenTargets)
- **Pathway enrichment analysis** with one-click biological interpretation
- **AI-generated summaries** explaining mechanisms and significance
- **Suggested follow-up queries** to continue exploring the knowledge graph

Built on **Neo4j** + **fine-tuned LLMs** for text-to-Cypher translation. Results are traceable, exportable, and validated against clinical evidence.

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

## Complete Workflow Example

### KRAS Resistance in Colorectal Cancer

This demonstrates OncoGraph's end-to-end workflow for understanding therapy resistance and finding alternatives.

**Step 1: Identify Resistance Mechanisms**  
Query: *"Which genes predict resistance to cetuximab or panitumumab in colorectal cancer?"*  
→ **Result:** 13 genes (KRAS, NRAS, BRAF, ERBB2, PIK3CA, etc.) with 88 evidence items across 45 PMIDs

**Step 2: Understand Biological Mechanism**  
Action: Click "Move to Hypothesis Analyzer"  
→ **Result:** Enrichment in ErbB signaling pathway (p < 1e-19)  
→ **AI Summary:** "These genes converge on receptor tyrosine kinase signaling. Dysregulation allows tumor cells to maintain proliferative signals despite EGFR blockade."

**Step 3: Find Alternative Therapeutic Targets**  
Action: Click suggested query *"Which therapies target ERBB2, MAP2K1, or PIK3CA?"*  
→ **Result:** ERBB2 inhibitors (trastuzumab, pertuzumab), MEK inhibitors (trametinib, cobimetinib), PI3K inhibitors (alpelisib, copanlisib)

**Insight:** Patients with anti-EGFR resistance may benefit from combination strategies targeting downstream pathways.

**Time:** ~7 minutes from question to actionable hypothesis | **Manual equivalent:** 45-60 minutes

---

## What Problem Does This Solve?

When computational models predict a gene signature affects drug response, researchers need to:
1. **Validate** - Is this finding supported by clinical evidence?
2. **Interpret** - What biological mechanism explains this pattern?
3. **Act** - What therapies target this mechanism?

This typically requires hours of manual work across multiple tools.

**OncoGraph integrates the entire workflow:**
- Query clinical evidence in natural language
- Interpret biological mechanisms via pathway enrichment
- Explore therapeutic options through the knowledge graph
- All with traceable sources and exportable results

**Complements AI discovery platforms:** When models (e.g., Noetik's OCTO) predict gene signatures from spatial data, OncoGraph validates them against clinical evidence, interprets the mechanism, and identifies therapeutic options

---

## Key Features

**🔍 Natural Language Graph Queries**
- **Ask questions in plain English** about genes, variants, therapies, diseases
- **LLM generates Cypher** → executes on Neo4j knowledge graph
- **Results include** PMIDs, sources, interactive visualization, and raw Cypher
- **One-click export** of genes to Hypothesis Analyzer

**🧬 Pathway Enrichment Analysis**
- **Over-representation analysis** via Enrichr (Reactome 2022, GO BP 2023, KEGG 2021)
- **Dot plot visualization** of enriched pathways
- **AI-generated summary** explaining biological significance
- **Suggested follow-up queries** that execute in Graph Q&A tab

**🔄 Integrated Workflow**
- **Seamless transitions:** Query → Enrichment → Follow-up → Repeat
- **All sources traceable** to PMIDs

**✅ Transparent by Design**
- **Display raw Cypher** and raw results for validation

---

## Data Sources

**CIViC** (Clinical Interpretations of Variants in Cancer) - Variant-level evidence of therapy response (sensitivity/resistance) with PubMed IDs  
**OpenTargets** - Therapy → gene TARGETS relationships and mechanism of action tags

---

## Scope and Limitations
- **Public, curated data only** - not exhaustive  
- **Evidence stored on relationships** (no reified evidence graph in V1)  
- **For research and education only** - do not use for clinical decisions

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

OncoGraph has been validated against established clinical findings:

**KRAS Mutations in Anti-EGFR Therapy**  
Correctly identified 28+ KRAS variants (G12D, G12V, G13D, etc.) predicting cetuximab resistance in colorectal cancer. Cross-referenced with landmark study PMID:17363584 (Di Nicolantonio et al., 2008).

**BRAF-Targeted Therapies**  
Matches FDA-approved BRAF inhibitors (dabrafenib, vemurafenib, encorafenib) and current NCCN guidelines for BRAF-mutant cancers.

*OncoGraph is a research tool. Validate all results against primary literature before clinical application.*

---


## Fine-Tuned Models (Text-to-Cypher)

OncoGraph includes **fine-tuned LLMs** that translate natural language oncology questions directly into Cypher queries:

| Model | Accuracy | Latency | Best For |
|-------|----------|---------|----------|
| **Qwen3-4B-Oncograph** | 91.25% | ~14s | Highest accuracy |
| **Qwen3-1.7B-Oncograph** | 72.5% | ~9.9s | Speed/accuracy balance |

**📊 [View comprehensive evaluation results →](https://ib565.github.io/OncoGraph/model_evaluation_report.html)**

**Documentation:** [Overview](docs/FINETUNING_OVERVIEW.md) | [Technical Details](docs/FINETUNING_DETAILS.md)

Models available on Hugging Face as 16-bit merged models (vLLM-compatible) and LoRA adapters. *Note: Fine-tuned models not yet deployed; looking for cost-effective inference options.*

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

## Local Development

**Prerequisites:** Python 3.10+, Neo4j, Node.js

**Quick setup:**
```bash
# 1. Setup Python environment
python -m venv venv && source venv/bin/activate  # or .\venv\Scripts\activate on Windows
pip install -r requirements.txt && pip install -e .

# 2. Ingest CIViC data
python -m src.pipeline.civic_ingest --out-dir data/civic/latest --enrich-tags

# 3. Seed database
python -m src.graph.builder

# 4. Install frontend dependencies (once)
cd web && npm install && cd ..

# 5. Install dev tooling (once; installs concurrently)
npm install

# 6. Start both backend (port 8000) and frontend (port 3000)
npm run dev
```

Already ran `npm install` inside `web/`? You're set—repeat step 3 only when the UI package.json changes. Step 4 still needs to run once at the project root to pull in the root-level tooling.

Prefer separate terminals instead of the combined command?
```bash
# Terminal 1 - Backend
uvicorn api.main:app --reload

# Terminal 2 - Frontend
cd web && npm run dev
```

**Environment variables:** Create `.env` with `GOOGLE_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

See [TECHNICAL_DETAILS.md](docs/TECHNICAL_DETAILS.md) for full setup instructions, testing, and architecture details

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

## For Developers

Want to understand the internals? See [**TECHNICAL_DETAILS.md**](docs/TECHNICAL_DETAILS.md)

---

## Roadmap
- **Fine tune a model for Cypher generation.** ✅ Completed - See [Fine-Tuning Overview](docs/FINETUNING_OVERVIEW.md)
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
