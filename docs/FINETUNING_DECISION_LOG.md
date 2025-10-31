# Fine-Tuning Decision Log

This document chronicles the key decisions, abandoned ideas, and final strategies adopted during the development of the fine-tuning dataset for the OncoGraph agent. It serves as a narrative of the iterative process of refining the data generation strategy.

## 1. Initial Goal & Strategy

**Decision:** Replace the existing two-step Gemini-based LLM chain with a single, fine-tuned model for direct text-to-Cypher generation.

**Rationale:** To improve latency, reduce cost, and increase domain-specific accuracy. This also serves as a high-impact portfolio project demonstrating end-to-end AI engineering.

## 2. Refining Query Coverage

**Initial State:** A set of query "families" (F1-F4) was defined to cover basic lookups, set operations, and multi-hop queries.

**Problem:** A review against the `README.md`'s real-world example queries revealed significant gaps. The initial plan did not explicitly handle queries filtered by **disease context** (e.g., "...in colorectal cancer") or queries for **node properties** (e.g., "what is the modality of...").

**Decision:** Expand the query families to include `F5: Disease-Centric Queries` and new sub-families under `F2` to handle property-based lookups. This ensures the training data covers the full range of demonstrated product capabilities.

## 3. The Core Challenge: Handling Disease Names

The most complex part of this process was designing a robust strategy for handling user queries about diseases, which can be phrased in many ways.

### Iteration 1: The Data Enrichment "Detour"

**Initial Question:** The `disease_name` on relationships is a simple string, making it hard to query with synonyms. Should we denormalize the data by adding a list of synonyms to every relationship?

**Decision:** **No.** This was rejected as a classic data modeling anti-pattern. It would lead to massive data duplication, poor integrity, and maintenance nightmares. The correct approach is to keep the graph schema normalized.

**Refined Decision:** We decided to enrich the `Disease` nodes themselves by ingesting their aliases from the CIViC data source. This was a crucial, high-value "detour" that fixed the data at the source. This enriched data would not be used for direct graph queries but would become the "knowledge base" for the dataset generation script.

### Iteration 2: The "Hacky" Approach & Its Flaws

**Initial Idea (The "Smart Token" approach):** The model should learn when to generate a broad, high-recall query versus a specific, high-precision query. For "lung cancer," it should search broadly (`CONTAINS 'lung'`), but for "non-small cell lung cancer," it should search precisely.

**Problem:** This approach became increasingly complex and "hacky." It required curating lists of "umbrella terms" and created ambiguous rules. A critical flaw was discovered: it would incorrectly treat `"Breast Cancer"` and `"Breast Carcinoma"` as the same broad query, even though they are distinct canonical entities in the data. This violated data integrity and would produce incorrect results.

### Iteration 3: The Final, Clean Solution

**The Breakthrough:** The final and cleanest solution was to move the "intelligence" out of the LLM and into a simple, deterministic rule within the `generate_dataset.py` script.

**The "Cancer" Rule:**
1.  The LLM's **only job** is to map the user's phrasing to the most appropriate canonical disease name from the database (a simple translation task).
2.  The dataset generator then uses a single, hard-coded rule to create the "gold" Cypher query:
    > When tokenizing a canonical disease name, if the word `"cancer"` is present and it is not the only word, remove it from the list of tokens used to build the query.

**Rationale & Final State:**
- This rule is deterministic, simple, and testable.
- For `"Lung Cancer"`, it correctly generates a high-recall query (`CONTAINS 'lung'`).
- For `"Lung Carcinoma"`, it correctly generates a high-precision query (`CONTAINS 'lung' AND CONTAINS 'carcinoma'`).
- For `"Cancer"`, it correctly generates a precise query (`CONTAINS 'cancer'`).
- This approach is not hacky because the logic is explicit in our code, not hoped for from the LLM. The model is given a much simpler, cleaner task, which will lead to a more reliable result.

### Implementation Details: Order-Invariant Token Matching

**Enhancement:** To handle disease name variations in the database (e.g., "Lung Non-small Cell Carcinoma" vs "Non-small Cell Lung Carcinoma"), queries use order-invariant token matching. All tokens from the canonical disease name are AND-ed together, ensuring matches regardless of word order.

**Example:** For `"Non-small Cell Lung Carcinoma"`, the generator creates:
```cypher
WHERE (
  toLower(rel.disease_name) CONTAINS 'lung' AND
  toLower(rel.disease_name) CONTAINS 'non-small' AND
  toLower(rel.disease_name) CONTAINS 'cell' AND
  toLower(rel.disease_name) CONTAINS 'carcinoma'
)
```

This matches both "Lung Non-small Cell Carcinoma" and "Non-small Cell Lung Carcinoma" in the database, maximizing recall while maintaining precision through multiple token requirements. Hyphens are preserved in tokens (e.g., "non-small" remains as a single token) to match dataset conventions.