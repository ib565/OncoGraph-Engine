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

### Iteration 4: Teaching Synonym Recognition Through Data Augmentation

**Problem:** While the model learns to map user queries to canonical disease names, real-world queries often use alternative disease name phrasings (synonyms). For example, users might ask about "Non-small Cell Lung Carcinoma" or "Lung Non-small Cell Carcinoma" interchangeably, or use clinical synonyms like "NSCLC" for the same disease entity.

**Decision:** Augment the training dataset with question variants that use disease synonyms from the CIViC data source, while keeping the Cypher queries unchanged (always using canonical names). This teaches the model that multiple disease name variations map to the same ground truth canonical entity.

**Implementation Strategy:**
1. Load disease synonyms from CIViC's `diseases.csv` file during dataset generation.
2. For each generated record containing a disease name:
   - Always generate the canonical question (as baseline).
   - Randomly sample 1 to N synonyms (configurable, default: 3) and generate additional question variants.
   - Questions use synonyms in natural language, but Cypher queries always reference the canonical disease name.
3. Maintain consistent ID scheme: canonical records use base IDs (e.g., `F1-000123`), synonym variants use `-S<N>` suffix (e.g., `F1-000123-S1`).
4. Paraphrase templates apply to both canonical and synonym variants, ensuring comprehensive coverage.

**Rationale:**
- **Separation of Concerns:** The model learns synonym mapping (user phrasing → canonical name) while Cypher generation remains deterministic and consistent.
- **Data Augmentation:** This naturally expands the training dataset with realistic variations users might employ.
- **Ground Truth Consistency:** By keeping `placeholders` in records as canonical names, we maintain a single source of truth while training on diverse question phrasings.
- **Controlled Growth:** The number of synonym variants per disease is configurable via environment variable to balance dataset size with training diversity.

**Example:** For a disease with canonical name "Lung Non-small Cell Carcinoma" and synonyms ["Non-small Cell Lung Carcinoma", "NSCLC"], the generator creates:
- Canonical question: "What genes are associated with Lung Non-small Cell Carcinoma?"
- Synonym variant 1: "What genes are associated with Non-small Cell Lung Carcinoma?"
- Synonym variant 2: "What genes are associated with NSCLC?"

All three use the same Cypher query filtering on the canonical disease name, teaching the model that these phrasings are equivalent.

## 5. Evaluation Architecture: Model-Agnostic Design with Protocol-Based Adapters

**Problem:** The initial evaluation notebook (`02_evaluate_baselines.ipynb`) had hardcoded logic for Gemini and Qwen models, making it difficult to:
- Evaluate multiple models in a single run
- Add new models without duplicating code
- Reuse evaluation logic for fine-tuned models
- Maintain consistent checkpointing and results analysis across models

**Decision:** Implement a **model-agnostic evaluation architecture** using Python's `Protocol`-based design pattern.

**Architecture Components:**

1. **`ModelAdapter` Protocol** (`finetuning/eval/model_adapters.py`):
   - Defines a structural interface (`Protocol` with `@runtime_checkable`) that any model adapter must implement
   - Required methods: `generate_cypher()`, `count_tokens()`, `get_model_id()`, `get_full_prompt()`
   - Benefits: Type-safe, enables duck typing, no inheritance hierarchy needed

2. **Concrete Adapter Implementations**:
   - `GeminiModelAdapter`: Wraps Gemini 2-step pipeline (instruction expansion + Cypher generation), handles rate limiting (15 RPM), supports multiple Gemini models (`gemini-2.0-flash`, `gemini-2.5-flash-lite`)
   - `QwenModelAdapter`: Wraps Unsloth FastLanguageModel, handles Qwen chat template formatting, supports base and fine-tuned models

3. **Unified Evaluation Harness** (`finetuning/eval/harness.py`):
   - `Evaluator` class: Takes any `ModelAdapter`, performs syntactic validation, execution, and result comparison
   - `run_evaluation()` function: Orchestrates evaluation loop with checkpointing, progress tracking, and error handling
   - Model-specific checkpoint files: `{model_id}_checkpoint.jsonl` enables independent resumption per model

4. **Notebook as Orchestration Layer** (`02_evaluate_baselines.ipynb`):
   - Configuration cell: `MODELS_TO_RUN = ["gemini-2.0-flash", "gemini-2.5-flash-lite", "qwen3-4b-base"]`
   - Factory function: `create_model_adapter()` automatically instantiates the correct adapter based on model ID
   - Single evaluation loop: Iterates through models, calls `run_evaluation()` for each
   - Unified results analysis: Loads checkpoints from all evaluated models, generates comparison tables

**Rationale:**
- **Separation of Concerns:** Model-specific logic (inference, token counting, prompt formatting) encapsulated in adapters; evaluation logic (validation, execution, comparison) centralized in harness
- **Extensibility:** Adding a new model requires only creating a new adapter class implementing the `ModelAdapter` protocol
- **Reusability:** Same harness works for baseline and fine-tuned models; `04_evaluate_finetuned.ipynb` can reuse the same code
- **Checkpointing:** Model-specific checkpoint files allow independent resumption and flexible post-analysis
- **Type Safety:** Protocol ensures adapters implement required interface, catching errors at development time

**Benefits Realized:**
- Single notebook can evaluate 1-N models with identical code
- Easy to add new models (e.g., Claude, GPT-4) by creating new adapter
- Consistent metrics and checkpointing across all models
- Notebook can be interrupted and resumed seamlessly
- Fine-tuned model evaluation reuses the same harness (no code duplication)