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
- 2–3 PubMed citations  

---

## MVP Architecture

- **Data layer:**
- **Seed data:** small CSVs in `data/manual/`
- **Q&A layer:** user question → LLM → Cypher → Neo4j → citations → response
- **Traces:** every query and response saved for later fine‑tuning  

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