# OncoGraph Agent - Fine-Tuning Execution Plan

This document outlines the end-to-end plan for fine-tuning, evaluating, and deploying a bespoke Text-to-Cypher model for the OncoGraph Agent. It follows the data generation strategy detailed in `FINETUNING_PLAN.md` and focuses on the practical steps of model training and evaluation.

**Model:** `unsloth/Qwen3-4B-Instruct-2507-bnb-4bit` (A 4-bit quantized version of Qwen3-4B-Instruct optimized for Unsloth)
**Framework:** Unsloth for efficient, memory-optimized fine-tuning.

---

## Part 1: Project Setup & Organization

To maintain clarity and reproducibility, the `finetuning` directory will be organized with **Jupyter notebooks as the primary interface** for training and evaluation. This approach provides seamless portability between local execution and Google Colab, following the pattern established by Unsloth's example notebooks.

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
├── notebooks/
│   ├── 01_prepare_dataset.ipynb      # (Optional) Interactive version of dataset prep
│   ├── 02_evaluate_baselines.ipynb   # Evals Gemini and base Qwen
│   ├── 03_finetune.ipynb             # Runs Unsloth fine-tuning (primary training notebook)
│   └── 04_evaluate_finetuned.ipynb   # Evals the fine-tuned Qwen model
├── scripts/
│   └── prepare_dataset.py            # (Optional) Simple preprocessing script for automation
└── requirements-finetune.txt         # Specific Python packages for this workflow
```

### Why Notebooks?

**Notebooks are the primary interface because they:**
- **Seamlessly work in Colab:** Upload or clone the notebook, mount Drive, and run—no code changes needed
- **Enable interactive debugging:** See outputs, metrics, and model info inline without managing log files
- **Support easy experimentation:** Modify hyperparameters in a cell and re-run without restarting
- **Provide visualization:** Display training curves, comparison tables, and sample outputs directly
- **Simplify checkpoint management:** If training is interrupted, modify one cell to resume and re-execute
- **Match Unsloth examples:** All Unsloth tutorials use notebooks, so following this pattern ensures compatibility

---

## Part 2: Step-by-Step Workflow

### Step 1: Create a Diverse Data Subset

To balance training efficiency with data quality, we will create a smaller, representative subset of the full 32k+ records. This avoids simple random sampling, which could miss rare query patterns.

**Options:**
- **Quick/automated:** Run `python finetuning/scripts/prepare_dataset.py` (if the script exists)
- **Interactive:** Use `finetuning/notebooks/01_prepare_dataset.ipynb` for interactive exploration and visualization

**Action:**
1.  **Implement Stratified Sampling:** Scan all `generated_pairs.*.jsonl` files and group records by their `template_id`.
2.  **Create Subset:** Sample a fixed percentage (e.g., 20%) of records from each group. This ensures all query "families" (F1-F6) are proportionally represented.
3.  **Train-Test Split:** Split the subset again (e.g., 85% train, 15% test) into `train_sample.jsonl` and `test_sample.jsonl`.
4.  **Save to `splits/`:** Save the final datasets to `finetuning/dataset/splits/`.

### Step 2: Evaluate Baselines for Comparison (`02_evaluate_baselines.ipynb`)

A robust evaluation requires comparing our new model against existing solutions. This notebook establishes the performance benchmarks and can be run both locally and in Google Colab.

**Action:**
1.  **Setup Section:** Mount Google Drive (if in Colab) or configure local paths. Install dependencies and import required modules.
2.  **Define Evaluation Harness:** Implement the multi-level metrics defined in `FINETUNING_DATASET_PLAN.md`:
    *   **Syntactic Validity:** Passes the `RuleBasedValidator`.
    *   **Execution Success:** Runs on Neo4j without error.
    *   **Semantic Accuracy:** Returns the exact same result set as the "gold" Cypher query.
    *   **Average Latency (ms).**
3.  **Evaluate Current Gemini API:** Iterate through `test_sample.jsonl`, send each question to the existing Gemini pipeline, and run the output through the harness. Display progress and results inline.
4.  **Evaluate Base Qwen Model:** Load the untuned `Qwen3-4B-Instruct-2507` model using Unsloth. For each question in the test set, generate a Cypher query and evaluate it with the same harness. Display metrics inline.
5.  **Log Results:** Store the aggregated metrics for both baselines in `finetuning/eval/evaluation_results.json` and display a comparison table in the notebook.

### Step 3: Fine-Tune the Qwen Model (`03_finetune.ipynb`)

This is the core training notebook, designed for flexibility between local execution (for quick tests) and Google Colab (for full runs). It follows the structure of the Unsloth example notebooks for easy portability.

**Action:**
1.  **Setup Section:** 
    *   Mount Google Drive (if in Colab) or configure local paths.
    *   Install Unsloth and dependencies.
    *   Configure paths for data and model output (easily adjustable at the top of the notebook).
2.  **Load Quantized Model:** Use Unsloth to load the 4-bit quantized version of the Qwen model for maximum memory efficiency. Display model info inline.
3.  **Prepare Data:** 
    *   Load `train_sample.jsonl` and format each `(question, cypher)` pair into the required Qwen chat template, including a system prompt:
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
    *   Use Unsloth's `FastLanguageModel.get_peft_model()` and configure LoRA parameters.
4.  **Configure Trainer:** Use the Hugging Face `SFTTrainer` with `TrainingArguments` configured for:
    *   **Checkpointing:** Save progress periodically (e.g., every N steps) to a configurable checkpoint directory (default: `finetuning/models/checkpoints/` or Google Drive path). This allows training to be resumed if interrupted.
    *   **Logging:** Enable Weights & Biases or TensorBoard logging (optional) for visualization.
5.  **Run Training:** Start the training process. The notebook will display training progress and metrics inline. If interrupted, you can modify the training cell to resume from the latest checkpoint using `trainer.train(resume_from_checkpoint=True)`.
6.  **Save Adapters:** Upon completion, save the final LoRA adapters to the configured output directory (`finetuning/models/qwen_oncograph_v1/` or Google Drive). Display a confirmation message.

### Step 4: Evaluate the Fine-Tuned Model (`04_evaluate_finetuned.ipynb`)

This final step measures the success of our fine-tuning effort against the established baselines. The notebook can be run locally or in Colab.

**Action:**
1.  **Setup Section:** Mount Google Drive (if in Colab) or configure local paths. Load the evaluation harness code from Step 2 (can be copied or imported).
2.  **Load Fine-Tuned Model:** Load the base Qwen model with Unsloth, then apply the trained LoRA adapters from the saved directory (`finetuning/models/qwen_oncograph_v1/` or Google Drive path).
3.  **Run Evaluation:** Use the identical evaluation harness and test set (`test_sample.jsonl`) from Step 2 to process each question. Display progress and intermediate results inline.
4.  **Compare Results:** Load the baseline results from `finetuning/eval/evaluation_results.json` and append the fine-tuned model metrics. Display a comprehensive comparison table showing all three models (Gemini, Base Qwen, Fine-Tuned Qwen) side-by-side.
5.  **Save Final Results:** Update `evaluation_results.json` with the complete comparison data.

---

## Part 3: Tooling and Environment Management

To ensure a smooth workflow, especially when switching between local and cloud environments:

*   **Requirements File:** A `requirements-finetune.txt` is provided, including `unsloth`, `transformers[torch]`, `peft`, `trl`, `bitsandbytes`, and `scikit-learn`. This allows for one-command environment setup (`pip install -r finetuning/requirements-finetune.txt`).
*   **Path Configuration:** Notebooks use configuration cells at the top where paths can be easily adjusted. For Colab, paths typically point to mounted Google Drive directories. For local execution, paths point to the project's `finetuning/` directory.
*   **Google Colab Workflow:** 
    1.  Open Colab: Go to [colab.research.google.com](https://colab.research.google.com)
    2.  Upload notebook: File → Upload Notebook, or clone from GitHub if repository is public
    3.  First cell (setup):
        ```python
        from google.colab import drive
        drive.mount('/content/drive')
        
        # Clone repository or navigate to uploaded files
        # %cd /content/drive/MyDrive/OncoGraph-Agent  # or your path
        ```
    4.  Second cell (install dependencies):
        ```python
        !pip install -r finetuning/requirements-finetune.txt
        # Or install unsloth directly: !pip install unsloth[colab-new]
        ```
    5.  Path configuration cell (adjust as needed):
        ```python
        # Paths for Colab (pointing to Google Drive)
        BASE_DIR = "/content/drive/MyDrive/OncoGraph-Agent"
        DATA_DIR = f"{BASE_DIR}/finetuning/dataset/splits"
        MODEL_DIR = f"{BASE_DIR}/finetuning/models"
        CHECKPOINT_DIR = f"{BASE_DIR}/finetuning/models/checkpoints"
        ```
    6.  Execute remaining cells sequentially. All outputs (checkpoints, results) save to Drive automatically.

*   **Local Jupyter Workflow:**
    1.  Install Jupyter: `pip install jupyter notebook`
    2.  Navigate to project: `cd "path/to/OncoGraph Agent"`
    3.  Launch Jupyter: `jupyter notebook finetuning/notebooks/`
    4.  Path configuration cell (adjust as needed):
        ```python
        # Paths for local execution
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parents[2]  # Project root
        DATA_DIR = BASE_DIR / "finetuning" / "dataset" / "splits"
        MODEL_DIR = BASE_DIR / "finetuning" / "models"
        CHECKPOINT_DIR = BASE_DIR / "finetuning" / "models" / "checkpoints"
        ```
    5.  Execute cells as normal. All outputs save locally.

**Switching Between Environments:** The only difference is the path configuration cell at the top of each notebook. Simply comment/uncomment the appropriate section depending on whether you're running locally or in Colab.

**Benefits of Notebook-Based Approach:**
*   **Seamless Colab Integration:** Notebooks work natively in Colab, making GPU access trivial.
*   **Interactive Debugging:** See outputs, metrics, and model info inline without managing separate log files.
*   **Easy Experimentation:** Modify hyperparameters or data paths in a cell and re-run without restarting.
*   **Visualization:** Display training curves, comparison tables, and sample outputs directly in the notebook.
*   **Checkpoint Resumption:** If training is interrupted, simply modify the training cell to resume from checkpoint and re-execute.
