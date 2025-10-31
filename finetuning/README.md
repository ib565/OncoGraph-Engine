## OncoGraph Finetuning Package

This folder is an isolated, installable package for dataset generation and paraphrasing used in finetuning.

### 1) Install (editable)

Windows PowerShell:

```
./venv/Scripts/python.exe -m pip install -e ./finetuning
```

macOS/Linux:

```
./venv/bin/python -m pip install -e ./finetuning
```

After this, imports like `oncograph_finetuning...` will work from anywhere in the repo.

### 2) Optional: enable paraphrasing via Gemini

Set your API key and install the client:

Windows PowerShell:

```
$env:GEMINI_API_KEY = "<your-key>"
./venv/Scripts/python.exe -m pip install google-genai
```

macOS/Linux:

```
export GEMINI_API_KEY="<your-key>"
./venv/bin/python -m pip install google-genai
```

Generate paraphrases for one or more templates (writes `<template>.paraphrases.yaml` next to each template). Use `--all` or no args to process every template in the templates folder:

Windows:

```
./venv/Scripts/python.exe finetuning/scripts/paraphrase_templates.py --all

# Or specify explicit files
./venv/Scripts/python.exe finetuning/scripts/paraphrase_templates.py \
  f1_1_targets_gene.yaml f1_2_genes_for_therapy.yaml
```

macOS/Linux:

```
./venv/bin/python finetuning/scripts/paraphrase_templates.py --all

# Or specify explicit files
./venv/bin/python finetuning/scripts/paraphrase_templates.py \
  f1_1_targets_gene.yaml f1_2_genes_for_therapy.yaml
```

Templates live in:

```
finetuning/oncograph_finetuning/dataset_generation/templates/
```

### 3) Generate the dataset

The generator reads templates and automatically includes paraphrases if a sibling
`<template>.paraphrases.yaml` exists.

Windows:

```
./venv/Scripts/python.exe finetuning/scripts/generate_dataset.py --all
```

Single template:

```
./venv/Scripts/python.exe finetuning/scripts/generate_dataset.py f1_2_genes_for_therapy.yaml
```

macOS/Linux:

```
./venv/bin/python finetuning/scripts/generate_dataset.py --all
```

Outputs are written to:

```
finetuning/dataset/generated_pairs.<template_id>.jsonl
```

### Notes

- CIViC data is read from `data/civic/latest/...` in the repo by default.
- The package name is `oncograph-finetuning`; the import namespace is `oncograph_finetuning`.

