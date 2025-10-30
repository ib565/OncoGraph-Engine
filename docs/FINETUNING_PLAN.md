# OncoGraph Agent - Fine-Tuning Plan

This document outlines the strategy and steps for fine-tuning a bespoke language model for the Text-to-Cypher generation task in the OncoGraph Agent.

## 1. Overview & Goal

The current system uses a two-step LLM chain (Instruction Expansion → Cypher Generation) with a general-purpose model (Gemini). While effective, this approach can be improved in terms of latency, cost, and accuracy for our specific domain.

**Goal:** To replace the current system with a single, fine-tuned model that directly translates a user's natural language question into a safe, executable Cypher query. This will serve as a high-impact portfolio piece demonstrating end-to-end AI engineering capabilities.

## 2. Dataset Strategy: Hybrid Generation & Curation

We will create a high-quality dataset of `(question, cypher)` pairs using a hybrid approach that combines systematic generation for coverage and manual curation for realism.

### Step 1: Systematic Generation
- **Method:** We will write Python-based template generators for a comprehensive set of query "families" (see below). These templates will be populated with real entity data (genes, diseases, etc.) sampled from the project's existing CSV files. The generation script will leverage canonical entity names and their ingested synonyms (especially for diseases) to create a rich training set. For a single "gold" Cypher query targeting a canonical disease name (e.g., "Lung Non-small Cell Carcinoma"), the script will generate multiple varied questions using both the canonical name and its aliases (e.g., "non-small cell lung cancer"). This teaches the model to map diverse user phrasing to a single, robust query pattern.
- **Output:** ~1000-2000 `(question, gold_cypher)` pairs. The Cypher is considered "gold" because it's generated from deterministic, correct templates, not an LLM.

### Step 2: Question Curation and Dataset Finalization
- **Method:** After generating the `(question, gold_cypher)` pairs, the list of questions will be exported for manual review. This ensures linguistic quality and diversity.
- **Task:** The human curator will review and edit the list of generated questions to improve their naturalness and realism. The corresponding "gold" Cypher for each question remains unchanged.
- **Output:** A final, curated set of pairs, which will then be split into `train.jsonl` and `test.jsonl`.

## 3. Query Families

To ensure comprehensive coverage of the graph's capabilities, the dataset will be generated based on the following query patterns. The families are structured from simple lookups to complex, multi-hop reasoning.

#### F1: Basic Entity Lookups (1-hop)
- **F1.1 (Therapy -> Gene):** Therapies targeting a specific `Gene`.
  - *Example:* "What drugs target BRAF?"
- **F1.2 (Gene -> Therapy):** Genes targeted by a specific `Therapy` (Symmetric pattern).
  - *Example:* "Which genes does Dabrafenib target?"
- **F1.3 (Variant -> Gene):** The `Gene` a specific `Variant` belongs to.
  - *Example:* "Which gene is BRAF V600E a variant of?"
- **F1.4 (Gene -> Variants):** All `Variants` of a specific `Gene`.
  - *Example:* "List all known variants of the KRAS gene."

#### F2: Property-Based & Evidential Queries
- **F2.1 (TARGETS Properties):** Requesting properties from the `TARGETS` relationship.
  - *Example:* "What is Dabrafenib's mechanism of action on BRAF?"
- **F2.2 (AFFECTS_RESPONSE_TO Basic):** The effect of a `Biomarker` on a `Therapy`, often constrained by a `Disease`.
  - *Example:* "How does EGFR T790M affect response to Osiminib in lung cancer?"
- **F2.3 (Evidential Properties):** Requesting specific evidence details from the `AFFECTS_RESPONSE_TO` relationship.
  - *Example:* "Provide PMIDs supporting that EGFR S492R confers resistance to cetuximab."
- **F2.4 (Node Properties):** Requesting properties from a node itself, often combined with a lookup.
    - *Example:* "What are the tags for therapies that target BRAF?"

#### F3: Set-Based & Comparative Queries
- **F3.1 (Union):** Therapies targeting `Gene A` OR `Gene B`.
  - *Example:* "Find therapies for EGFR or ERBB2."
- **F3.2 (Intersection):** Therapies targeting `Gene A` AND `Gene B`.
  - *Example:* "What therapies target both BRAF and MEK1?"
- **F3.3 (Negative / Subtractive):** Therapies targeting `Gene A` but NOT `Gene B`.
  - *Example:* "Which drugs target KRAS but not NRAS?"

#### F4: Multi-Hop & Validation Queries (High Value)
- **F4.1 (Target Validation):** Find therapies that `TARGET` a specific `Gene` AND have known `AFFECTS_RESPONSE_TO` biomarker evidence in a `Disease`.
  - *Example:* "Which therapies target BRAF and also have biomarker evidence in melanoma?"
- **F4.2 (Alternative Therapy Discovery):** Find `Genes` that are resistance biomarkers for `Therapy A`, then find other therapies (`Therapy B`) that `TARGET` those `Genes`.
  - *Example:* "For therapies causing resistance via KRAS mutations, what are some alternative drugs targeting KRAS?"

#### F5: Disease-Centric & Discovery Queries
- **F5.1 (Disease -> Biomarkers):** Find all biomarkers (Genes or Variants) with evidence in a specific `Disease`.
  - *Example:* "In colorectal cancer, which ERBB2 or EGFR variants have biomarker evidence?"
- **F5.2 (Disease -> Therapies):** Find all therapies that have known biomarker evidence in a specific `Disease`.
  - *Example:* "List therapies with variant-level biomarkers in non-small cell lung cancer."

## 4. Key Generation Strategies

To ensure the model is robust to variations in user phrasing, the dataset will be designed to teach the following specific Cypher generation patterns:

### Disease Name Filtering

The model will be trained to translate varied user phrasing for diseases into a single, canonical, token-based Cypher query.

- **Training Data Process:**
  1.  For a given disease in the graph (e.g., `disease_name: "Lung Non-small Cell Carcinoma"`), define its "gold" Cypher query by tokenizing its canonical name.
  2.  Look up the disease's ingested aliases (e.g., "non-small cell lung cancer").
  3.  Generate multiple `(question, gold_cypher)` training pairs. The questions will use both the canonical name and its aliases, but the target Cypher will always be the same canonical, token-based query.
- **Inference-Time Goal:** This trains the model to act as a "translator." It learns that when a user asks about "non-small cell lung cancer," it must generate the precise Cypher query that filters for the canonical tokens: `['lung', 'non-small', 'cell', 'carcinoma']`.
- **Example Gold Cypher:**
  ```cypher
  ...
  WHERE toLower(rel.disease_name) CONTAINS toLower('lung')
    AND toLower(rel.disease_name) CONTAINS toLower('non-small')
    AND toLower(rel.disease_name) CONTAINS toLower('cell')
    AND toLower(rel.disease_name) CONTAINS toLower('carcinoma')
  ...
  ```
This makes the matching logic explicit in the training data, rather than relying on the model's implicit world knowledge.

## 5. Development Workflow & Tooling

All development will occur within this mono-repo to maintain tight integration with existing schema and validation logic.

### Directory Structure
```
.
├── scripts/
│   ├── generate_dataset.py   # Systematically generates (question, cypher) pairs
│   ├── execute_queries.py    # Executes cypher and stores results for validation
│   ├── split_dataset.py      # Script to split the curated data into train/test sets
│   ├── train_model.py        # Runs the fine-tuning job
│   └── evaluate_model.py     # Runs the evaluation harness on the test set
├── dataset/
│   ├── generated_pairs.jsonl
│   ├── executed_results.jsonl
│   └── final_dataset/        # Contains train.jsonl and test.jsonl
├── src/
│   ├── pipeline/
│   │   ├── local_model.py    # New file for the fine-tuned generator component
...
```

### Process
1.  Run `generate_dataset.py` to create the initial set of pairs.
2.  Manually review and edit the generated questions for quality and naturalness.
3.  Run `split_dataset.py` to create the final `train` and `test` splits.
4.  Run `train_model.py` using the `train.jsonl` file.
5.  Run `evaluate_model.py` on `test.jsonl` to benchmark the new model.

## 6. Evaluation Plan

Model performance will be assessed using a dedicated, held-out test set (~15-20% of the curated data). The evaluation script will be separate from the application's main tracing/logging system.

### Multi-Level Metrics
The script will report on the following metrics for the fine-tuned model vs. the baseline Gemini model:

1.  **Syntactic Validity:** Percentage of generated queries that pass the `RuleBasedValidator`.
2.  **Execution Success:** Percentage of valid queries that execute on Neo4j without error.
3.  **Semantic Accuracy (Result Matching):** Percentage of executed queries that return the **exact same result set** as the "gold" Cypher query from the test set. This is the primary measure of success.
4.  **Performance:** Average latency (ms) per query.

The results will be printed in a comparison table to clearly demonstrate the fine-tuned model's performance.
