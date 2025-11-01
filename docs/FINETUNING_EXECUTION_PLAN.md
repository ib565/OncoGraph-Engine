# OncoGraph Agent - Fine-Tuning Execution Plan

This document outlines the end-to-end plan for fine-tuning, evaluating, and deploying a bespoke Text-to-Cypher model for the OncoGraph Agent. It follows the data generation strategy detailed in `FINETUNING_PLAN.md` and focuses on the practical steps of model training and evaluation.

**Model:** `unsloth/Qwen3-4B-Instruct-2507-bnb-4bit` (A 4-bit quantized version of Qwen3-4B-Instruct optimized for Unsloth)
**Framework:** Unsloth for efficient, memory-optimized fine-tuning.

---

## Part 1: Project Setup & Organization

To maintain clarity and reproducibility, the `finetuning` directory will be organized with dedicated scripts and artifacts for each stage of the process.

### Directory Structure

```
finetuning/
├── dataset/
│   ├── generated_pairs.f1_1...jsonl  # Original, full generated datasets
│   └── splits/
│       ├── train_sample.jsonl        # (Output) The smaller training set for tuning
│       └── test_sample.jsonl         # (Output) The held-out test set for evaluation
├── eval/
│   └── evaluation_results.json       # (Output) Stores metrics for all models
├── models/
│   ├── checkpoints/                  # (Output) Intermediate training checkpoints
│   └── qwen_oncograph_v1/            # (Output) Final trained model adapters (LoRA)
├── scripts/
│   ├── 01_prepare_dataset.py         # (New) Creates the subset and splits
│   ├── 02_evaluate_baselines.py      # (New) Evals Gemini and base Qwen
│   ├── 03_finetune.py                # (New) Runs Unsloth fine-tuning
│   └── 04_evaluate_finetuned.py      # (New) Evals the fine-tuned Qwen model
└── requirements-finetune.txt         # (New) Specific Python packages for this workflow
```

---

## Part 2: Step-by-Step Workflow

### Step 1: Create a Diverse Data Subset (`01_prepare_dataset.py`)

To balance training efficiency with data quality, we will create a smaller, representative subset of the full 32k+ records. This avoids simple random sampling, which could miss rare query patterns.

**Action:**
1.  **Implement Stratified Sampling:** The script will scan all `generated_pairs.*.jsonl` files and group records by their `template_id`.
2.  **Create Subset:** It will then sample a fixed percentage (e.g., 20%) of records from each group. This ensures all query "families" (F1-F6) are proportionally represented.
3.  **Train-Test Split:** The resulting subset will be split again (e.g., 85% train, 15% test) into `train_sample.jsonl` and `test_sample.jsonl`.
4.  **Save to `splits/`:** The final, smaller datasets will be saved to `finetuning/dataset/splits/`.

### Step 2: Evaluate Baselines for Comparison (`02_evaluate_baselines.py`)

A robust evaluation requires comparing our new model against existing solutions. This script establishes the performance benchmarks.

**Action:**
1.  **Define Evaluation Harness:** The script will implement the multi-level metrics defined in `FINETUNING_PLAN.md`:
    *   **Syntactic Validity:** Passes the `RuleBasedValidator`.
    *   **Execution Success:** Runs on Neo4j without error.
    *   **Semantic Accuracy:** Returns the exact same result set as the "gold" Cypher query.
    *   **Average Latency (ms).**
2.  **Evaluate Current Gemini API:** Iterate through `test_sample.jsonl`, send each question to the existing Gemini pipeline, and run the output through the harness.
3.  **Evaluate Base Qwen Model:** Load the untuned `Qwen3-4B-Instruct-2507` model using Unsloth. For each question in the test set, generate a Cypher query and evaluate it with the same harness.
4.  **Log Results:** Store the aggregated metrics for both baselines in `finetuning/eval/evaluation_results.json`.

### Step 3: Fine-Tune the Qwen Model (`03_finetune.py`)

This is the core training script, designed for flexibility between local execution (for quick tests) and Google Colab (for full runs).

**Action:**
1.  **Load Quantized Model:** Use Unsloth to load the 4-bit quantized version of the Qwen model for maximum memory efficiency.
2.  **Format Data:** The script will load `train_sample.jsonl` and format each `(question, cypher)` pair into the required Qwen chat template, including a system prompt.
    ```
    <|im_start|>system
    You are an expert Cypher query translator. Given a user's question about oncology, provide the corresponding Cypher query.
    <|im_end|>
    <|im_start|>user
    {question}
    <|im_end|>
    <|im_start|>assistant
    {cypher}
    <|im_end|>
    ```
3.  **Configure Trainer:** Use the Hugging Face `SFTTrainer` with `TrainingArguments` configured for:
    *   **Checkpointing:** Save progress periodically (e.g., every N steps) to the `finetuning/models/checkpoints/` directory. This allows training to be resumed if interrupted.
    *   **Flexibility:** All paths (data, output) will be configurable via command-line arguments to easily switch between local and Colab file systems.
4.  **Run Training:** Start the training process. The script should support a `resume_from_checkpoint` flag.
5.  **Save Adapters:** Upon completion, the script will save the final LoRA adapters to `finetuning/models/qwen_oncograph_v1/`.

### Step 4: Evaluate the Fine-Tuned Model (`04_evaluate_finetuned.py`)

This final step measures the success of our fine-tuning effort against the established baselines.

**Action:**
1.  **Load Fine-Tuned Model:** Load the base Qwen model with Unsloth, then apply the trained LoRA adapters from `finetuning/models/qwen_oncograph_v1/`.
2.  **Run Evaluation:** Use the identical evaluation harness and test set (`test_sample.jsonl`) from Step 2 to process each question.
3.  **Append Results:** Add the performance metrics of the fine-tuned model to `finetuning/eval/evaluation_results.json`. This file will then contain a complete comparison of all three models, providing a clear view of the performance gains.

---

## Part 3: Tooling and Environment Management

To ensure a smooth workflow, especially when switching between local and cloud environments:

*   **Requirements File:** A `requirements-finetune.txt` will be created, including `unsloth`, `transformers[torch]`, `peft`, `trl`, and `bitsandbytes`. This allows for one-command environment setup (`pip install -r ...`).
*   **Command-Line Arguments:** All scripts will use Python's `argparse` module to handle file paths and key parameters, eliminating the need for hardcoded paths.
*   **Google Colab Workflow:** When using Colab, the recommended process is to mount Google Drive, clone the repository, install dependencies, and run the scripts with paths pointing to the mounted Drive for data and model persistence.
