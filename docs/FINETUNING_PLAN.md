# OncoGraph Agent - Fine-Tuning Plan

This document outlines the strategy and steps for fine-tuning a bespoke language model for the Text-to-Cypher generation task in the OncoGraph Agent.

## 1. Overview & Goal

The current system uses a two-step LLM chain (Instruction Expansion → Cypher Generation) with a general-purpose model (Gemini). While effective, this approach can be improved in terms of latency, cost, and accuracy for our specific domain.

**Goal:** To replace the current system with a single, fine-tuned model that directly translates a user's natural language question into a safe, executable Cypher query. This will serve as a high-impact portfolio piece demonstrating end-to-end AI engineering capabilities.

## 2. Dataset Strategy: Hybrid Generation & Curation

We will create a high-quality dataset of `(question, cypher)` pairs using a hybrid approach that combines systematic generation for coverage and manual curation for realism.

### Step 1: Systematic Generation
- **Method:** We will write Python-based template generators for a comprehensive set of query "families" (see below). These templates will be populated with real entity data (genes, diseases, etc.) sampled from the project's existing CSV files. A variety of natural language questions will be generated for each "gold" Cypher query.
- **Output:** ~1000-2000 `(question, gold_cypher)` pairs. The Cypher is considered "gold" because it's generated from deterministic, correct templates, not an LLM.

### Step 2: Question Curation and Dataset Finalization
- **Method:** After generating the `(question, gold_cypher)` pairs, the list of questions will be exported for manual review. This ensures linguistic quality and diversity.
- **Task:** The human curator will review and edit the list of generated questions to improve their naturalness and realism. The corresponding "gold" Cypher for each question remains unchanged.
- **Output:** A final, curated set of pairs, which will then be split into `train.jsonl` and `test.jsonl`.

## 3. Query Families

To ensure comprehensive coverage of the graph's capabilities, the dataset will be generated based on the following query patterns:

#### F1: Simple Lookups (1-hop)
- **F1.1 (Targets):** Therapies targeting a specific `Gene`.
  - *Example:* "What drugs target BRAF?"
- **F1.2 (Targets with Properties):** Therapies targeting a `Gene`, requesting properties like `moa`.
  - *Example:* "What is the mechanism of action of dabrafenib?"
- **F1.3 (Biomarker Effect):** Effect of a specific `Variant` on a `Therapy` in a `Disease`.
  - *Example:* "Does KRAS G12C predict resistance to Cetuximab in colorectal cancer?"
- **F1.4 (Biomarker Discovery):** `Genes` or `Variants` predicting response to a `Therapy` for a `Disease`.
  - *Example:* "Which genes are resistance biomarkers for immunotherapy in melanoma?"

#### F2: Set-based Queries
- **F2.1 (Union):** Therapies targeting `Gene A` OR `Gene B`.
  - *Example:* "Find therapies for EGFR or ERBB2."
- **F2.2 (Intersection):** Therapies targeting `Gene A` AND `Gene B`.
  - *Example:* "What therapies target both BRAF and MEK1?"

#### F3: Comparative & Negative Queries
- **F3.1 (Comparative Effect):** Therapies with biomarkers for both `Sensitivity` AND `Resistance`.
  - *Example:* "Which therapies have conflicting evidence for biomarkers?"
- **F3.2 (Negative Targeting):** Therapies targeting `Gene A` but NOT `Gene B`.
  - *Example:* "Which drugs target KRAS but not NRAS?"

#### F4: Multi-Hop Queries (2-hops)
- **F4.1 (Biomarker to Alternative Therapy):** Find `Genes` that are resistance biomarkers for `Therapy A`, then find other therapies (`Therapy B`) that target those `Genes`.
  - *Example:* "For anti-EGFR resistance, what other therapies target the involved genes?"

## 4. Development Workflow & Tooling

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

## 5. Evaluation Plan

Model performance will be assessed using a dedicated, held-out test set (~15-20% of the curated data). The evaluation script will be separate from the application's main tracing/logging system.

### Multi-Level Metrics
The script will report on the following metrics for the fine-tuned model vs. the baseline Gemini model:

1.  **Syntactic Validity:** Percentage of generated queries that pass the `RuleBasedValidator`.
2.  **Execution Success:** Percentage of valid queries that execute on Neo4j without error.
3.  **Semantic Accuracy (Result Matching):** Percentage of executed queries that return the **exact same result set** as the "gold" Cypher query from the test set. This is the primary measure of success.
4.  **Performance:** Average latency (ms) per query.

The results will be printed in a comparison table to clearly demonstrate the fine-tuned model's performance.
